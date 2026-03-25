#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桥接服务核心，整合所有功能
"""
import asyncio
import json
import hmac
import hashlib
import time
from typing import Dict, Optional, Callable, Any
from loguru import logger
from .telegram_client import create_telegram_client, BotTelegramClient
from .redis_manager import get_redis_manager
from .utils import async_retry


class TelegramBridgeService:
    """Telegram 桥接服务核心"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get('mode', 'bot')
        self.telegram_config = config.get('telegram', {})
        self.redis = get_redis_manager(config.get('redis', {}))
        self.webhook_config = config.get('webhook', {})
        self.max_retry = self.telegram_config.get('max_send_retry', 3)
        
        # 创建默认Telegram客户端
        self.client = create_telegram_client(config, self._on_receive_message)
        
        # 动态Bot客户端缓存 {token: BotTelegramClient}
        self._bot_clients_cache: Dict[str, BotTelegramClient] = {}
        self._cache_lock = asyncio.Lock()
        
        # 运行状态
        self.running = False
        self._consumer_task: Optional[asyncio.Task] = None
        
        logger.info(f"🌉 Telegram桥接服务初始化完成，运行模式: {self.mode}")
    
    async def start(self):
        """启动服务，带网络异常重试"""
        self.running = True
        max_start_retry = self.telegram_config.get('max_start_retry', 5)
        start_retry_interval = self.telegram_config.get('start_retry_interval', 5)
        
        # 启动发送任务消费者
        self._consumer_task = asyncio.create_task(self._consume_send_tasks())
        logger.info("📥 发送任务消费协程已启动")
        
        # 启动Telegram客户端，使用统一重试逻辑
        logger.info(f"🚀 尝试启动Telegram客户端，最多重试{max_start_retry}次...")
        await async_retry(
            self.client.start,
            max_retries=max_start_retry,
            retry_interval=start_retry_interval
        )
        logger.info("✅ Telegram客户端启动成功")
    
    async def stop(self):
        """停止服务"""
        self.running = False
        
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        
        # 停止默认客户端
        await self.client.stop()
        
        # 停止所有自定义Bot客户端
        async with self._cache_lock:
            for token, client in self._bot_clients_cache.items():
                try:
                    await client.stop()
                    logger.debug(f"🛑 已停止自定义Bot客户端，Token前缀: {token[:10]}...")
                except Exception as e:
                    logger.warning(f"停止自定义Bot客户端失败: {str(e)}")
        
        logger.info("👋 桥接服务已停止")
    
    # ==================== 对外接口 ====================
    def send_message(self, task_data: Dict) -> str:
        """创建发送消息任务，返回任务ID"""
        return self.redis.create_send_task(task_data)
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """查询任务状态"""
        return self.redis.get_task_status(task_id)
    
    def retry_task(self, task_id: str) -> bool:
        """重试失败任务"""
        task = self.get_task_status(task_id)
        if not task:
            return False
        return self.redis.retry_task(task_id)
    
    def get_messages(self, chat_id: Optional[int] = None, limit: int = 100,
                    offset: int = 0, sender_id: Optional[int] = None) -> list:
        """获取接收的消息列表"""
        return self.redis.get_messages(chat_id, limit, offset, sender_id)
    
    def search_messages(self, keyword: str, chat_id: Optional[int] = None,
                       case_sensitive: bool = False, limit: int = 100) -> list:
        """搜索消息"""
        return self.redis.search_messages(keyword, chat_id, case_sensitive, limit)
    
    def get_message_by_id(self, chat_id: int, msg_id: int) -> Optional[Dict]:
        """根据ID获取消息"""
        return self.redis.get_message_by_id(chat_id, msg_id)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.redis.get_stats()
        stats['mode'] = self.mode
        stats['webhook_enabled'] = self.webhook_config.get('enabled', False)
        return stats
    
    async def _get_custom_bot_client(self, bot_token: str) -> BotTelegramClient:
        """
        获取自定义Bot Token对应的客户端，带缓存和初始化重试
        :param bot_token: Bot Token
        :return: Bot客户端实例
        """
        async with self._cache_lock:
            if bot_token in self._bot_clients_cache:
                return self._bot_clients_cache[bot_token]
            
            max_init_retry = self.telegram_config.get('max_init_retry', 3)
            init_retry_interval = self.telegram_config.get('init_retry_interval', 2)
            
            async def init_custom_bot():
                logger.info(f"🔌 初始化自定义Bot客户端，Token前缀: {bot_token[:10]}...")
                custom_config = self.config.copy()
                custom_config['bot']['token'] = bot_token
                # 自定义Bot不需要监听消息，所以传入空的回调
                client = BotTelegramClient(custom_config, lambda x: asyncio.sleep(0))
                # 初始化客户端
                await client.application.initialize()
                await client.application.start()
                return client
            
            # 使用统一重试逻辑初始化
            client = await async_retry(
                init_custom_bot,
                max_retries=max_init_retry,
                retry_interval=init_retry_interval
            )
            
            self._bot_clients_cache[bot_token] = client
            logger.info(f"✅ 自定义Bot客户端初始化成功，Token前缀: {bot_token[:10]}...")
            return client
    
    # ==================== 内部逻辑 ====================
    async def _save_sent_message(self, task: Dict, success: bool, message_id: Optional[int] = None, error_msg: str = "", client = None):
        """保存发送的消息（无论成功失败）"""
        try:
            # 获取Bot信息
            if not client:
                client = self.client
            bot_info = await client.application.bot.get_me()
            
            sent_message = {
                "message_id": message_id if message_id else int(time.time() * 1000),  # 失败的话用时间戳当临时ID
                "chat_id": task['chat_id'],
                "chat_title": "",
                "chat_type": "private",
                "sender_id": bot_info.id,
                "sender_name": f"{bot_info.first_name} {bot_info.last_name or ''}".strip(),
                "sender_username": bot_info.username or "",
                "is_bot": True,
                "text": task.get('text', task.get('caption', '')),
                "timestamp": int(time.time()),
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "has_media": 'media_type' in task,
                "media_type": task.get('media_type', ''),
                "source": "bot",
                "send_success": success,
                "error_msg": error_msg
            }
            # 保存到Redis
            await asyncio.to_thread(self.redis.save_received_message, sent_message)
            if success:
                logger.debug(f"✅ 已保存发送成功的消息: 任务ID={task['task_id']}, 消息ID={message_id}")
            else:
                logger.debug(f"✅ 已保存发送失败的消息: 任务ID={task['task_id']}, 错误: {error_msg}")
        except Exception as e:
            logger.warning(f"⚠️ 保存发送消息失败: {str(e)}")

    async def _consume_send_tasks(self):
        """消费发送任务队列"""
        logger.info("🔄 开始消费发送任务队列")
        while self.running:
            try:
                # 获取待发送任务
                task = await asyncio.to_thread(self.redis.get_pending_task)
                if not task:
                    await asyncio.sleep(0.1)
                    continue
                
                task_id = task['task_id']
                chat_id = task['chat_id']
                logger.info(f"⚡ 处理发送任务: {task_id} -> {chat_id}")
                
                # 选择发送客户端：优先用任务自带的Bot Token，否则用默认客户端
                custom_bot_token = task.get('bot_token')
                if custom_bot_token and self.mode == 'bot':
                    client = await self._get_custom_bot_client(custom_bot_token)
                else:
                    # User模式不支持自定义Token，使用默认客户端
                    client = self.client
                
                # 判断是文本消息还是媒体消息
                if task.get('media_type'):
                    # 媒体消息
                    result = await client.send_media(task)
                else:
                    # 文本消息
                    result = await client.send_message(task)
                
                # 更新任务状态
                if result['success']:
                    await asyncio.to_thread(
                        self.redis.update_task_status,
                        task_id,
                        'success',
                        '',
                        result['message_id']
                    )
                    
                    # 发送成功，清除媒体内容释放内存
                    await asyncio.to_thread(self.redis.clear_task_media, task_id)
                    
                    # 将发送成功的消息保存到消息存储
                    await self._save_sent_message(task, success=True, message_id=result['message_id'], client=client)
                else:
                    error_msg = result['error']
                    retry_count = task['retry_count']
                    
                    if retry_count < self.max_retry:
                        task['retry_count'] += 1
                        logger.warning(f"⚠️ 任务 {task_id} 发送失败，{retry_count+1}/{self.max_retry} 重试: {error_msg}")
                        await asyncio.to_thread(self.redis.update_task_status, task_id, 'failed', error_msg)
                        await asyncio.sleep(self.config.get('telegram', {}).get('retry_interval', 2))
                        await asyncio.to_thread(self.redis.retry_task, task_id)
                    else:
                        logger.error(f"❌ 任务 {task_id} 发送失败，已达最大重试次数: {error_msg}")
                        await asyncio.to_thread(self.redis.update_task_status, task_id, 'failed', error_msg)
                        # 最终发送失败，保存到消息存储
                        await self._save_sent_message(task, success=False, error_msg=error_msg, client=client)
                        # 最终发送失败，清除媒体内容释放内存
                        await asyncio.to_thread(self.redis.clear_task_media, task_id)
            
            except Exception as e:
                logger.error(f"💥 消费任务异常: {str(e)}")
                # 连接异常等情况，将任务重新放回队列重试
                if 'task' in locals() and task:
                    try:
                        task_id = task['task_id']
                        retry_count = task['retry_count']
                        if retry_count < self.max_retry:
                            logger.warning(f"♻️ 异常任务 {task_id} 重新入队重试，当前重试次数: {retry_count}/{self.max_retry}")
                            await asyncio.to_thread(self.redis.retry_task, task_id)
                        else:
                            logger.error(f"❌ 异常任务 {task_id} 已达最大重试次数，标记为失败")
                            await asyncio.to_thread(self.redis.update_task_status, task_id, 'failed', f"消费异常: {str(e)}")
                            # 最终发送失败，保存到消息存储
                            await self._save_sent_message(task, success=False, error_msg=str(e))
                    except Exception as retry_err:
                        logger.error(f"❌ 异常任务重试入队失败: {str(retry_err)}")
                await asyncio.sleep(1)
    
    async def _on_receive_message(self, message: Dict):
        """收到消息的回调处理"""
        try:
            # 保存到Redis
            await asyncio.to_thread(self.redis.save_received_message, message)
            
            # Webhook推送
            if self.webhook_config.get('enabled', False):
                asyncio.create_task(self._push_to_webhook(message))
        
        except Exception as e:
            logger.error(f"💥 处理接收消息异常: {str(e)}")
    
    async def _push_to_webhook(self, message: Dict):
        """推送消息到Webhook"""
        try:
            # 延迟导入aiohttp，只有在启用webhook时才加载
            import aiohttp
            url = self.webhook_config.get('url')
            secret = self.webhook_config.get('secret', '')
            timeout = self.webhook_config.get('timeout', 10)
            max_retry = self.webhook_config.get('max_retry', 3)
            retry_interval = self.webhook_config.get('retry_interval', 2)
            
            if not url:
                logger.warning("⚠️ Webhook URL未配置，跳过推送")
                return
            
            # 生成签名
            payload = json.dumps(message, ensure_ascii=False).encode('utf-8')
            signature = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest() if secret else ""
            
            headers = {
                'Content-Type': 'application/json',
                'X-Telegram-Bridge-Signature': signature
            }
            
            for retry in range(max_retry):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            data=payload,
                            headers=headers,
                            timeout=timeout
                        ) as resp:
                            if resp.status in (200, 201, 204):
                                logger.debug(f"✅ Webhook推送成功: 消息ID={message['message_id']}")
                                return
                            else:
                                logger.warning(f"⚠️ Webhook推送返回状态码 {resp.status}, 重试 {retry+1}/{max_retry}")
                except Exception as e:
                    logger.warning(f"⚠️ Webhook推送失败（第{retry+1}次）: {str(e)}")
                
                if retry < max_retry - 1:
                    await asyncio.sleep(retry_interval * (2 ** retry))  # 指数退避
            
            logger.error(f"❌ Webhook推送失败，已重试{max_retry}次: {url}")
        
        except Exception as e:
            logger.error(f"💥 Webhook推送异常: {str(e)}")


# 全局单例
_bridge_instance: Optional[TelegramBridgeService] = None


def get_bridge_service(config: Dict = None) -> TelegramBridgeService:
    global _bridge_instance
    if _bridge_instance is None and config is not None:
        _bridge_instance = TelegramBridgeService(config)
    return _bridge_instance
