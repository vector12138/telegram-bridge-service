#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 客户端，支持 Bot 和 User 双模式，整合收发功能
"""
import asyncio
import time
from typing import Dict, Optional, Callable, Any
from loguru import logger
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel


class BaseTelegramClient:
    """客户端基类"""
    
    def __init__(self, config: Dict, message_callback: Callable[[Dict], Any]):
        self.config = config
        self.telegram_config = config.get('telegram', {})
        self.message_callback = message_callback
        self.allowed_chat_ids = [str(cid) for cid in self.telegram_config.get('allowed_chat_ids', [])]
        self.max_retry = self.telegram_config.get('max_send_retry', 3)
        self.retry_interval = self.telegram_config.get('retry_interval', 2)
        self.listen_outgoing = self.telegram_config.get('listen_outgoing', False)
    
    async def start(self):
        """启动客户端"""
        raise NotImplementedError
    
    async def stop(self):
        """停止客户端"""
        raise NotImplementedError
    
    async def send_message(self, task: Dict) -> Dict:
        """发送消息，返回结果"""
        raise NotImplementedError
    
    def _is_chat_allowed(self, chat_id: int) -> bool:
        """检查聊天是否在白名单"""
        if not self.allowed_chat_ids:
            return True
        return str(chat_id) in self.allowed_chat_ids
    
    def _build_message_data(self, message_id: int, chat: Any, sender: Any, text: str,
                           timestamp: int, has_media: bool, media_type: str,
                           source: str = "") -> Dict:
        """构建统一的消息格式"""
        chat_title = ""
        chat_type = "unknown"
        
        # 处理聊天信息
        if hasattr(chat, 'title') and chat.title:
            chat_title = chat.title
        elif hasattr(chat, 'first_name') and chat.first_name:
            chat_title = chat.first_name + (f" {chat.last_name}" if hasattr(chat, 'last_name') and chat.last_name else "")
        else:
            chat_title = "私聊"
        
        if isinstance(chat, User):
            chat_type = "private"
        elif isinstance(chat, Chat):
            chat_type = "group"
        elif isinstance(chat, Channel):
            chat_type = "channel" if chat.broadcast else "supergroup"
        elif hasattr(chat, 'type'):
            chat_type = chat.type
        
        # 处理发送者信息
        sender_id = 0
        sender_name = "匿名"
        sender_username = ""
        is_bot = False
        
        if sender:
            sender_id = sender.id if hasattr(sender, 'id') else 0
            if hasattr(sender, 'first_name') and sender.first_name:
                sender_name = sender.first_name
                if hasattr(sender, 'last_name') and sender.last_name:
                    sender_name += f" {sender.last_name}"
            elif hasattr(sender, 'title') and sender.title:
                sender_name = sender.title
            else:
                sender_name = str(sender_id)
            
            sender_username = sender.username if hasattr(sender, 'username') and sender.username else ""
            is_bot = sender.bot if hasattr(sender, 'bot') else False
        
        return {
            "message_id": message_id,
            "chat_id": chat.id,
            "chat_title": chat_title,
            "chat_type": chat_type,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "sender_username": sender_username,
            "is_bot": is_bot,
            "text": text or "",
            "timestamp": timestamp,
            "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
            "has_media": has_media,
            "media_type": media_type,
            "source": source
        }


class BotTelegramClient(BaseTelegramClient):
    """Bot模式客户端"""
    
    def __init__(self, config: Dict, message_callback: Callable[[Dict], Any]):
        super().__init__(config, message_callback)
        bot_config = config.get('bot', {})
        self.token = bot_config.get('token')
        if not self.token:
            raise ValueError("Bot模式必须配置token")
        
        self.application = ApplicationBuilder().token(self.token).build()
        
        # 只有默认的主客户端才注册消息处理器，自定义客户端只用于发送
        if message_callback and hasattr(message_callback, '__call__'):
            # 注册处理器
            self.application.add_handler(MessageHandler(filters.ALL, self._handle_message))
            self.application.add_handler(CallbackQueryHandler(self._handle_callback))
            logger.info("🤖 主Bot客户端初始化完成，已注册消息监听")
        else:
            logger.info("🤖 自定义Bot客户端初始化完成，仅用于发送消息")
    
    async def start(self):
        """启动Bot，主客户端启动监听，自定义客户端只初始化不启动polling"""
        logger.info("🚀 初始化Telegram Bot客户端...")
        await self.application.initialize()
        await self.application.start()
        
        # 只有主客户端（有消息回调的）才启动polling监听消息
        if self.message_callback and hasattr(self.message_callback, '__call__'):
            drop_pending = self.config.get('bot', {}).get('drop_pending_updates', True)
            await self.application.updater.start_polling(drop_pending_updates=drop_pending)
            logger.info("✅ Bot服务启动成功，开始监听消息")
        else:
            logger.info("✅ 自定义Bot客户端初始化完成，仅用于发送消息")
    
    async def stop(self):
        """停止Bot"""
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("🛑 Bot服务已停止")
    
    async def send_message(self, task: Dict) -> Dict:
        """发送文本消息"""
        chat_id = task.get('chat_id')
        text = task.get('text', '')
        parse_mode = task.get('parse_mode', 'Markdown')
        disable_notification = task.get('disable_notification', False)
        
        if not chat_id or not text:
            return {"success": False, "error": "缺少chat_id或text参数"}
        
        if not self._is_chat_allowed(chat_id):
            return {"success": False, "error": f"聊天ID {chat_id} 不在白名单中"}
        
        for retry in range(self.max_retry):
            try:
                msg = await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode if parse_mode != "None" else None,
                    disable_notification=disable_notification
                )
                return {"success": True, "message_id": msg.message_id}
            except Exception as e:
                error = str(e)
                logger.warning(f"发送失败（第{retry+1}次重试）: {error}")
                if retry < self.max_retry - 1:
                    await asyncio.sleep(self.retry_interval)
        
        return {"success": False, "error": f"发送失败，已重试{self.max_retry}次: {error}"}
    
    async def send_media(self, task: Dict) -> Dict:
        """发送媒体消息，支持图片、文件、视频、音频等"""
        chat_id = task.get('chat_id')
        media_type = task.get('media_type')  # photo/document/video/audio/voice
        media = task.get('media')  # 文件路径、字节或者file_id
        caption = task.get('caption', '')
        parse_mode = task.get('parse_mode', 'Markdown')
        disable_notification = task.get('disable_notification', False)
        
        if not chat_id or not media_type or not media:
            return {"success": False, "error": "缺少chat_id、media_type或media参数"}
        
        if not self._is_chat_allowed(chat_id):
            return {"success": False, "error": f"聊天ID {chat_id} 不在白名单中"}
        
        send_method_map = {
            "photo": self.application.bot.send_photo,
            "document": self.application.bot.send_document,
            "video": self.application.bot.send_video,
            "audio": self.application.bot.send_audio,
            "voice": self.application.bot.send_voice
        }
        
        if media_type not in send_method_map:
            return {"success": False, "error": f"不支持的媒体类型: {media_type}"}
        
        send_method = send_method_map[media_type]
        
        for retry in range(self.max_retry):
            try:
                msg = await send_method(
                    chat_id=chat_id,
                    **{media_type: media},
                    caption=caption,
                    parse_mode=parse_mode if parse_mode != "None" else None,
                    disable_notification=disable_notification
                )
                return {"success": True, "message_id": msg.message_id}
            except Exception as e:
                error = str(e)
                logger.warning(f"发送{media_type}失败（第{retry+1}次重试）: {error}")
                if retry < self.max_retry - 1:
                    await asyncio.sleep(self.retry_interval)
        
        return {"success": False, "error": f"发送{media_type}失败，已重试{self.max_retry}次: {error}"}
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理收到的消息"""
        try:
            if not update.message:
                return
            
            chat = update.message.chat
            sender = update.message.from_user
            
            if not self._is_chat_allowed(chat.id):
                logger.debug(f"忽略非白名单聊天消息: {chat.id}")
                return
            
            # 提取媒体信息
            has_media = bool(update.message.photo or update.message.document or update.message.video or update.message.audio or update.message.voice)
            media_type = self._get_media_type(update.message)
            text = update.message.text or update.message.caption or ""
            
            message_data = self._build_message_data(
                message_id=update.message.message_id,
                chat=chat,
                sender=sender,
                text=text,
                timestamp=int(update.message.date.timestamp()),
                has_media=has_media,
                media_type=media_type,
                source="bot"
            )
            
            await self.message_callback(message_data)
        except Exception as e:
            logger.error(f"处理Bot消息失败: {str(e)}")
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理回调查询"""
        try:
            query = update.callback_query
            await query.answer()
            
            callback_data = {
                "type": "callback_query",
                "query_id": query.id,
                "chat_id": query.message.chat.id if query.message else 0,
                "message_id": query.message.message_id if query.message else 0,
                "sender_id": query.from_user.id,
                "sender_name": f"{query.from_user.first_name or ''} {query.from_user.last_name or ''}".strip(),
                "data": query.data,
                "timestamp": int(time.time()),
                "source": "bot"
            }
            
            await self.message_callback(callback_data)
        except Exception as e:
            logger.error(f"处理回调失败: {str(e)}")
    
    def _get_media_type(self, message) -> str:
        """获取媒体类型"""
        if message.photo:
            return "photo"
        elif message.document:
            return "document"
        elif message.video:
            return "video"
        elif message.audio:
            return "audio"
        elif message.voice:
            return "voice"
        else:
            return ""


class UserTelegramClient(BaseTelegramClient):
    """User模式客户端（个人账号）"""
    
    def __init__(self, config: Dict, message_callback: Callable[[Dict], Any]):
        super().__init__(config, message_callback)
        user_config = config.get('user', {})
        self.api_id = user_config.get('api_id')
        self.api_hash = user_config.get('api_hash')
        self.phone = user_config.get('phone_number')
        self.session_file = user_config.get('session_file', 'user_session.session')
        
        if not self.api_id or not self.api_hash or not self.phone:
            raise ValueError("User模式必须配置api_id、api_hash和phone_number")
        
        self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
        
        # 注册消息处理器
        event = events.NewMessage(incoming=not self.listen_outgoing, outgoing=self.listen_outgoing)
        self.client.add_event_handler(self._handle_message, event)
        
        logger.info("🧑 User模式客户端初始化完成")
    
    async def start(self):
        """启动User客户端"""
        logger.info("🚀 启动Telegram User客户端...")
        await self.client.start(phone=self.phone)
        logger.info("✅ User客户端启动成功，开始监听消息")
        await self.client.run_until_disconnected()
    
    async def stop(self):
        """停止User客户端"""
        await self.client.disconnect()
        logger.info("🛑 User客户端已停止")
    
    async def send_message(self, task: Dict) -> Dict:
        """发送消息"""
        chat_id = task.get('chat_id')
        text = task.get('text', '')
        parse_mode = task.get('parse_mode', 'md')
        disable_notification = task.get('disable_notification', False)
        
        if not chat_id or not text:
            return {"success": False, "error": "缺少chat_id或text参数"}
        
        if not self._is_chat_allowed(chat_id):
            return {"success": False, "error": f"聊天ID {chat_id} 不在白名单中"}
        
        for retry in range(self.max_retry):
            try:
                msg = await self.client.send_message(
                    entity=chat_id,
                    message=text,
                    parse_mode=parse_mode if parse_mode != "None" else None,
                    silent=disable_notification
                )
                return {"success": True, "message_id": msg.id}
            except Exception as e:
                error = str(e)
                logger.warning(f"发送失败（第{retry+1}次重试）: {error}")
                if retry < self.max_retry - 1:
                    await asyncio.sleep(self.retry_interval)
        
        return {"success": False, "error": f"发送失败，已重试{self.max_retry}次: {error}"}
    
    async def send_media(self, task: Dict) -> Dict:
        """发送媒体消息，支持图片、文件、视频、音频等"""
        chat_id = task.get('chat_id')
        media_type = task.get('media_type')  # photo/document/video/audio/voice
        media = task.get('media')  # 文件路径、字节或者file_id
        caption = task.get('caption', '')
        parse_mode = task.get('parse_mode', 'md')
        disable_notification = task.get('disable_notification', False)
        
        if not chat_id or not media_type or not media:
            return {"success": False, "error": "缺少chat_id、media_type或media参数"}
        
        if not self._is_chat_allowed(chat_id):
            return {"success": False, "error": f"聊天ID {chat_id} 不在白名单中"}
        
        for retry in range(self.max_retry):
            try:
                msg = await self.client.send_file(
                    entity=chat_id,
                    file=media,
                    caption=caption,
                    parse_mode=parse_mode if parse_mode != "None" else None,
                    silent=disable_notification
                )
                return {"success": True, "message_id": msg.id}
            except Exception as e:
                error = str(e)
                logger.warning(f"发送{media_type}失败（第{retry+1}次重试）: {error}")
                if retry < self.max_retry - 1:
                    await asyncio.sleep(self.retry_interval)
        
        return {"success": False, "error": f"发送{media_type}失败，已重试{self.max_retry}次: {error}"}
    
    async def _handle_message(self, event):
        """处理收到的消息"""
        try:
            message = event.message
            chat = await event.get_chat()
            sender = await event.get_sender()
            
            if not self._is_chat_allowed(chat.id):
                logger.debug(f"忽略非白名单聊天消息: {chat.id}")
                return
            
            has_media = message.media is not None
            media_type = message.media.__class__.__name__ if has_media else ""
            
            message_data = self._build_message_data(
                message_id=message.id,
                chat=chat,
                sender=sender,
                text=message.text or "",
                timestamp=int(message.date.timestamp()),
                has_media=has_media,
                media_type=media_type,
                source="user"
            )
            
            await self.message_callback(message_data)
        except Exception as e:
            logger.error(f"处理User消息失败: {str(e)}")


def create_telegram_client(config: Dict, message_callback: Callable[[Dict], Any]) -> BaseTelegramClient:
    """创建对应模式的客户端"""
    mode = config.get('mode', 'bot')
    if mode == 'bot':
        return BotTelegramClient(config, message_callback)
    elif mode == 'user':
        return UserTelegramClient(config, message_callback)
    else:
        raise ValueError(f"不支持的模式: {mode}，可选值: bot/user")
