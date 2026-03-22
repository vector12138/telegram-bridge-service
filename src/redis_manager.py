#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis 管理器，整合消息存储、任务队列、统计功能
"""
import json
import time
from typing import Dict, List, Optional, Any
import redis
from loguru import logger


class RedisManager:
    """Redis统一管理器"""
    
    def __init__(self, config: Dict):
        """初始化"""
        self.config = config
        self.host = config.get('host', '127.0.0.1')
        self.port = int(config.get('port', 6379))
        self.db = int(config.get('db', 2))
        self.password = config.get('password', '')
        self.prefix = config.get('key_prefix', 'telegram:bridge:')
        self.message_expire = int(config.get('message_expire', 86400 * 7))
        self.task_expire = int(config.get('task_expire', 86400 * 3))
        self.max_recent = int(config.get('max_recent_messages', 1000))
        
        # 连接Redis
        self.client = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password if self.password else None,
            decode_responses=True
        )
        
        # 测试连接
        try:
            self.client.ping()
            logger.info(f"✅ Redis连接成功: {self.host}:{self.port}/{self.db}")
        except Exception as e:
            logger.error(f"❌ Redis连接失败: {str(e)}")
            raise
    
    # ==================== 接收消息存储 ====================
    def save_received_message(self, message: Dict) -> bool:
        """保存接收的消息"""
        try:
            msg_id = message.get('message_id')
            chat_id = message.get('chat_id')
            if not msg_id or not chat_id:
                logger.error("消息缺少必填字段: message_id/chat_id")
                return False
            
            # 保存消息详情，转换bool类型为字符串适配Redis
            key = f"{self.prefix}msg:{chat_id}:{msg_id}"
            save_msg = message.copy()
            if 'is_bot' in save_msg:
                save_msg['is_bot'] = str(save_msg['is_bot'])
            if 'has_media' in save_msg:
                save_msg['has_media'] = str(save_msg['has_media'])
            self.client.hset(key, mapping=save_msg)
            self.client.expire(key, self.message_expire)
            
            # 添加到全局消息列表（有序集合，按时间排序）
            self.client.zadd(f"{self.prefix}msg:all", {f"{chat_id}:{msg_id}": message['timestamp']})
            
            # 添加到聊天维度的消息列表
            self.client.zadd(f"{self.prefix}msg:chat:{chat_id}", {str(msg_id): message['timestamp']})
            
            # 自动清理旧消息
            self._cleanup_old_messages()
            
            logger.debug(f"📥 消息保存成功: 聊天={chat_id}, ID={msg_id}, 发送者={message.get('sender_name', '未知')}")
            return True
        except Exception as e:
            logger.error(f"保存消息失败: {str(e)}")
            return False
    
    def get_message_by_id(self, chat_id: int, msg_id: int) -> Optional[Dict]:
        """根据聊天ID和消息ID获取消息"""
        try:
            key = f"{self.prefix}msg:{chat_id}:{msg_id}"
            msg = self.client.hgetall(key)
            return self._format_message(msg) if msg else None
        except Exception as e:
            logger.error(f"获取消息失败: {str(e)}")
            return None
    
    def get_messages(self, chat_id: Optional[int] = None, limit: int = 100, offset: int = 0,
                    sender_id: Optional[int] = None) -> List[Dict]:
        """
        获取消息列表，按时间倒序
        :param chat_id: 可选，按聊天ID过滤
        :param limit: 返回数量，默认100
        :param offset: 偏移量
        :param sender_id: 可选，按发送者ID过滤
        """
        try:
            limit = min(limit, 1000)
            messages = []
            
            if chat_id:
                # 获取指定聊天的消息
                zkey = f"{self.prefix}msg:chat:{chat_id}"
                start = -(offset + limit)
                end = -offset - 1 if offset > 0 else -1
                msg_ids = self.client.zrange(zkey, start, end)
                msg_ids = list(reversed(msg_ids))
                
                for msg_id in msg_ids:
                    msg = self.get_message_by_id(chat_id, int(msg_id))
                    if msg and (not sender_id or msg['sender_id'] == sender_id):
                        messages.append(msg)
            else:
                # 获取全局消息
                zkey = f"{self.prefix}msg:all"
                start = -(offset + limit)
                end = -offset - 1 if offset > 0 else -1
                msg_keys = self.client.zrange(zkey, start, end)
                msg_keys = list(reversed(msg_keys))
                
                for key in msg_keys:
                    chat_id_str, msg_id_str = key.split(':')
                    msg = self.get_message_by_id(int(chat_id_str), int(msg_id_str))
                    if msg:
                        if sender_id and msg['sender_id'] != sender_id:
                            continue
                        messages.append(msg)
            
            return messages[:limit]
        except Exception as e:
            logger.error(f"获取消息列表失败: {str(e)}")
            return []
    
    def search_messages(self, keyword: str, chat_id: Optional[int] = None,
                       case_sensitive: bool = False, limit: int = 100) -> List[Dict]:
        """搜索包含关键词的消息"""
        try:
            messages = self.get_messages(chat_id=chat_id, limit=1000)
            result = []
            
            for msg in messages:
                text = msg.get('text', '')
                if not case_sensitive:
                    keyword = keyword.lower()
                    text = text.lower()
                
                if keyword in text:
                    result.append(msg)
                    if len(result) >= limit:
                        break
            
            return result
        except Exception as e:
            logger.error(f"搜索消息失败: {str(e)}")
            return []
    
    # ==================== 发送任务管理 ====================
    def create_send_task(self, task_data: Dict) -> str:
        """创建发送任务，返回任务ID"""
        try:
            task_id = f"{int(time.time() * 1000)}_{hash(str(task_data)) & 0xFFFFFF}"
            # 基础任务字段
            task = {
                "task_id": task_id,
                "chat_id": str(task_data['chat_id']),
                "parse_mode": task_data.get('parse_mode', 'Markdown'),
                "disable_notification": str(task_data.get('disable_notification', False)),
                "bot_token": task_data.get('bot_token', ''),
                "status": "pending",
                "created_at": str(time.time()),
                "retry_count": "0",
                "error_msg": ""
            }
            
            # 文本消息字段
            if 'text' in task_data:
                task['text'] = task_data['text']
            # 媒体消息字段
            if 'media_type' in task_data:
                task['media_type'] = task_data['media_type']
                task['media'] = task_data['media'] if isinstance(task_data['media'], str) else json.dumps(task_data['media'])
                task['caption'] = task_data.get('caption', '')
            
            # 保存任务详情
            key = f"{self.prefix}task:{task_id}"
            self.client.hset(key, mapping=task)
            self.client.expire(key, self.task_expire)
            
            # 加入待发送队列
            self.client.rpush(f"{self.prefix}queue:pending", task_id)
            
            logger.info(f"📤 发送任务创建成功: ID={task_id}, 目标={task['chat_id']}, 类型={'媒体' if 'media_type' in task else '文本'}")
            return task_id
        except Exception as e:
            logger.error(f"创建发送任务失败: {str(e)}")
            return ""
    
    def get_pending_task(self) -> Optional[Dict]:
        """获取待发送任务（阻塞弹出）"""
        try:
            res = self.client.blpop(f"{self.prefix}queue:pending", timeout=1)
            if not res:
                return None
            
            _, task_id = res
            key = f"{self.prefix}task:{task_id}"
            task = self.client.hgetall(key)
            
            return self._format_task(task) if task else None
        except Exception as e:
            logger.error(f"获取待发送任务失败: {str(e)}")
            return None
    
    def update_task_status(self, task_id: str, status: str, error_msg: str = "",
                          message_id: Optional[int] = None) -> bool:
        """更新任务状态"""
        try:
            key = f"{self.prefix}task:{task_id}"
            if not self.client.exists(key):
                logger.error(f"任务不存在: {task_id}")
                return False
            
            update_data = {
                "status": status,
                "updated_at": str(time.time())
            }
            
            if error_msg:
                update_data['error_msg'] = error_msg
            if message_id:
                update_data['message_id'] = str(message_id)
            if status == "failed":
                retry_count = int(self.client.hget(key, 'retry_count'))
                update_data['retry_count'] = str(retry_count + 1)
            
            self.client.hset(key, mapping=update_data)
            logger.info(f"🔄 任务状态更新: {task_id} -> {status}")
            return True
        except Exception as e:
            logger.error(f"更新任务状态失败: {str(e)}")
            return False
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        try:
            key = f"{self.prefix}task:{task_id}"
            task = self.client.hgetall(key)
            return self._format_task(task) if task else None
        except Exception as e:
            logger.error(f"获取任务状态失败: {str(e)}")
            return None
    
    def retry_task(self, task_id: str) -> bool:
        """重新加入队列重试"""
        try:
            key = f"{self.prefix}task:{task_id}"
            if not self.client.exists(key):
                return False
            
            self.client.rpush(f"{self.prefix}queue:pending", task_id)
            self.update_task_status(task_id, "pending")
            logger.info(f"♻️ 任务重新入队: {task_id}")
            return True
        except Exception as e:
            logger.error(f"重试任务失败: {str(e)}")
            return False
    
    # ==================== 统计信息 ====================
    def get_stats(self) -> Dict:
        """获取系统统计"""
        try:
            total_messages = self.client.zcard(f"{self.prefix}msg:all")
            pending_tasks = self.client.llen(f"{self.prefix}queue:pending")
            total_tasks = len(self.client.keys(f"{self.prefix}task:*"))
            
            return {
                "total_received_messages": total_messages,
                "pending_send_tasks": pending_tasks,
                "total_send_tasks": total_tasks,
                "max_stored_messages": self.max_recent,
                "redis_connected": True
            }
        except Exception as e:
            logger.error(f"获取统计失败: {str(e)}")
            return {"error": str(e)}
    
    # ==================== 内部方法 ====================
    def _cleanup_old_messages(self):
        """清理超出数量限制的旧消息"""
        try:
            total = self.client.zcard(f"{self.prefix}msg:all")
            if total <= self.max_recent:
                return
            
            delete_count = total - self.max_recent
            # 删除最早的消息
            old_msg_keys = self.client.zrange(f"{self.prefix}msg:all", 0, delete_count - 1)
            
            for key in old_msg_keys:
                chat_id, msg_id = key.split(':')
                self.client.delete(f"{self.prefix}msg:{chat_id}:{msg_id}")
                self.client.zrem(f"{self.prefix}msg:chat:{chat_id}", msg_id)
            
            self.client.zremrangebyrank(f"{self.prefix}msg:all", 0, delete_count - 1)
            logger.info(f"🧹 清理了{delete_count}条旧消息，当前存储{self.max_recent}条")
        except Exception as e:
            logger.error(f"清理旧消息失败: {str(e)}")
    
    def _format_message(self, msg: Dict) -> Dict:
        """格式化消息字段类型"""
        for field in ['message_id', 'chat_id', 'sender_id', 'timestamp']:
            if field in msg:
                msg[field] = int(msg[field])
        if 'is_bot' in msg:
            msg['is_bot'] = msg['is_bot'] == 'True'
        if 'has_media' in msg:
            msg['has_media'] = msg['has_media'] == 'True'
        return msg
    
    def _format_task(self, task: Dict) -> Dict:
        """格式化任务字段类型"""
        for field in ['chat_id', 'created_at', 'updated_at', 'retry_count', 'message_id']:
            if field in task and task[field]:
                task[field] = int(float(task[field])) if '.' in task[field] else int(task[field])
        if 'disable_notification' in task:
            task['disable_notification'] = task['disable_notification'] == 'True'
        # 媒体字段处理：如果是JSON字符串反序列化
        if 'media' in task:
            try:
                task['media'] = json.loads(task['media'])
            except:
                # 不是JSON，保留原始字符串（比如file_id、URL）
                pass
        return task


# 全局单例
_redis_instance: Optional[RedisManager] = None


def get_redis_manager(config: Dict = None) -> RedisManager:
    global _redis_instance
    if _redis_instance is None and config is not None:
        _redis_instance = RedisManager(config)
    return _redis_instance
