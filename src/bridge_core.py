#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桥接服务核心，整合所有功能
"""
import asyncio
import json
import hmac
import hashlib
import aiohttp
from typing import Dict, Optional
from loguru import logger
from .telegram_client import create_telegram_client
from .redis_manager import get_redis_manager


from telegram.ext import ApplicationBuilder
from .telegram_client import BotTelegramClient
import asyncio
from typing import Dict, Optional, Callable, Any
from loguru import logger


class TelegramBridgeService:
    """Telegram 桥接服务核心"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get('mode', 'bot')
        self.redis = get_redis_manager(config.get('redis', {}))
        self.webhook_config = config.get('webhook', {})
        self.max_retry = config.get('telegram', {}).get('max_send_retry', 3)
        
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
        """启动服务"""
        self.running = True
        
        # 启动发送任务消费者
        self._consumer_task = asyncio.create_task(self._consume_send_tasks())
        logger.info("📥 发送任务消费协程已启动")
        
        # 启动Telegram客户端
        await self.client.start()
    
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
        获取自定义Bot Token对应的客户端，带缓存
        :param bot_token: Bot Token
        :return: Bot客户端实例
        """
        async with self._cache_lock:
            if bot_token in self._bot_clients_cache:
                return self._bot_clients_cache[bot_token]
            
            # 创建新的Bot客户端
            logger.info(f"🔌 创建新的自定义Bot客户端，Token前缀: {bot_token[:10]}...")
            custom_config = self.config.copy()
            custom_config['bot']['token'] = bot_token
            # 自定义Bot不需要监听消息，所以传入空的回调
            client = BotTelegramClient(custom_config, lambda x: asyncio.sleep(0))
            # 初始化客户端
            await client.application.initialize()
            await client.application.start()
            
            self._bot_clients_cache[bot_token] = client
            return client
    
    # ==================== 内部逻辑 ====================
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
                    result = await client.send_message(task)
                else:
                    # User模式不支持自定义Token，使用默认客户端
                    result = await self.client.send_message(task)
                
                # 更新任务状态
                if result['success']:
                    await asyncio.to_thread(
                        self.redis.update_task_status,
                        task_id,
                        'success',
                        '',
                        result['message_id']
                    )
                else:
                    error_msg = result['error']
                    retry_count = task['retry_count']
                    
                    if retry_count < self.max_retry:
                        logger.warning(f"⚠️ 任务 {task_id} 发送失败，{retry_count+1}/{self.max_retry} 重试: {error_msg}")
                        await asyncio.to_thread(self.redis.update_task_status, task_id, 'retrying', error_msg)
                        await asyncio.sleep(self.config.get('telegram', {}).get('retry_interval', 2))
                        await asyncio.to_thread(self.redis.retry_task, task_id)
                    else:
                        logger.error(f"❌ 任务 {task_id} 发送失败，已达最大重试次数: {error_msg}")
                        await asyncio.to_thread(self.redis.update_task_status, task_id, 'failed', error_msg)
            
            except Exception as e:
                logger.error(f"💥 消费任务异常: {str(e)}")
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
