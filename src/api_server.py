#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 服务层，整合所有接口
"""
import yaml
import time
import asyncio
import os
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status, Request, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from loguru import logger
import uvicorn
from .bridge_core import get_bridge_service


# 加载配置
def load_config(config_path: str = "config.yaml") -> Dict:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        raise


config = load_config()
api_config = config.get('api', {})
MAX_MEDIA_SIZE = api_config.get('max_media_size', 100 * 1024 * 1024)  # 默认100MB
bridge = get_bridge_service(config)

# 初始化FastAPI，生产模式关闭自动文档，减少内存占用
fastapi_kwargs = {
    "title": "Telegram Bridge Service API",
    "description": "完整的Telegram桥接服务API，支持消息收发、查询、搜索、任务管理",
    "version": "1.0.0",
    "debug": api_config.get('debug', False)
}
if not api_config.get('debug', False):
    fastapi_kwargs.update({
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None
    })

app = FastAPI(**fastapi_kwargs)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.get('cors_allow_origins', ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API密钥校验
API_KEY = api_config.get('api_key')
if not API_KEY:
    logger.warning("⚠️ 未配置api_key，接口将无鉴权，存在安全风险！")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    if API_KEY and api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的API密钥"
        )
    return api_key


# ==================== 数据模型 ====================
class SendMessageRequest(BaseModel):
    chat_id: int = Field(description="目标聊天ID")
    text: str = Field(description="消息内容")
    parse_mode: str = Field(default="Markdown", description="解析模式: Markdown/HTML/None")
    disable_notification: bool = Field(default=False, description="是否静默发送")
    bot_token: Optional[str] = Field(None, description="可选，自定义Bot Token，优先使用此Token发送，不填则使用配置默认Token")


class SendMessageResponse(BaseModel):
    task_id: str = Field(description="任务ID")
    status: str = Field(default="pending", description="任务状态")


class TaskStatusResponse(BaseModel):
    task_id: str = Field(description="任务ID")
    status: str = Field(description="状态: pending/retrying/success/failed")
    chat_id: int = Field(description="目标聊天ID")
    message_id: Optional[int] = Field(description="发送成功的消息ID")
    error_msg: Optional[str] = Field(description="错误信息")
    created_at: int = Field(description="创建时间戳")
    updated_at: Optional[int] = Field(description="更新时间戳")
    retry_count: int = Field(description="已重试次数")


class MessageResponse(BaseModel):
    message_id: int = Field(description="消息ID")
    chat_id: int = Field(description="聊天ID")
    chat_title: str = Field(description="聊天名称")
    chat_type: str = Field(description="聊天类型: private/group/supergroup/channel")
    sender_id: int = Field(description="发送者ID")
    sender_name: str = Field(description="发送者名称")
    sender_username: str = Field(description="发送者用户名")
    is_bot: bool = Field(description="是否是Bot")
    text: str = Field(description="消息内容")
    timestamp: int = Field(description="时间戳")
    date: str = Field(description="格式化时间")
    has_media: bool = Field(description="是否包含媒体")
    media_type: str = Field(description="媒体类型")
    source: str = Field(description="来源: bot/user")


class StatsResponse(BaseModel):
    mode: str = Field(description="运行模式: bot/user")
    total_received_messages: int = Field(description="总接收消息数")
    pending_send_tasks: int = Field(description="待发送任务数")
    total_send_tasks: int = Field(description="总发送任务数")
    max_stored_messages: int = Field(description="最大存储消息数")
    webhook_enabled: bool = Field(description="Webhook是否启用")
    redis_connected: bool = Field(description="Redis连接状态")


class SearchRequest(BaseModel):
    keyword: str = Field(description="搜索关键词")
    chat_id: Optional[int] = Field(None, description="可选，按聊天ID过滤")
    case_sensitive: bool = Field(False, description="是否区分大小写")
    limit: int = Field(100, ge=1, le=1000, description="返回数量")


# ==================== 接口路由 ====================
@app.get("/api/v1/health", summary="健康检查")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "timestamp": int(time.time())}


@app.get("/api/v1/stats", summary="获取服务统计", response_model=StatsResponse, dependencies=[Depends(verify_api_key)])
async def get_stats():
    """获取服务运行统计信息"""
    return bridge.get_stats()


# -------------------- 发送相关接口 --------------------
@app.post("/api/v1/message/send", summary="发送Telegram消息", response_model=SendMessageResponse, dependencies=[Depends(verify_api_key)])
async def send_message(request: SendMessageRequest):
    """
    发送Telegram消息，异步处理
    返回任务ID，可通过任务ID查询发送状态
    """
    task_id = bridge.send_message(request.dict())
    if not task_id:
        raise HTTPException(status_code=500, detail="创建发送任务失败")
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/v1/task/{task_id}", summary="查询任务状态", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
async def get_task_status(task_id: str):
    """根据任务ID查询发送状态"""
    task = bridge.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/v1/task/{task_id}/retry", summary="重试失败任务", dependencies=[Depends(verify_api_key)])
async def retry_task(task_id: str):
    """重新发送失败的任务"""
    success = bridge.retry_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在或重试失败")
    return {"status": "ok", "message": "任务已重新加入队列"}


# -------------------- 接收消息相关接口 --------------------
@app.get("/api/v1/message/received", summary="获取接收的消息列表", response_model=List[MessageResponse], dependencies=[Depends(verify_api_key)])
async def get_received_messages(
    chat_id: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量，最大1000"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    sender_id: Optional[int] = None
):
    """
    获取接收到的消息列表，按时间倒序排列
    - **chat_id**: 可选，按聊天ID过滤
    - **limit**: 返回数量，默认100
    - **offset**: 分页偏移量
    - **sender_id**: 可选，按发送者ID过滤
    """
    return bridge.get_messages(chat_id, limit, offset, sender_id)


@app.get("/api/v1/message/{chat_id}/{message_id}", summary="根据ID获取消息详情", response_model=MessageResponse, dependencies=[Depends(verify_api_key)])
async def get_message(chat_id: int, message_id: int):
    """根据聊天ID和消息ID获取消息详情"""
    msg = bridge.get_message_by_id(chat_id, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    return msg


@app.post("/api/v1/message/search", summary="搜索消息", response_model=List[MessageResponse], dependencies=[Depends(verify_api_key)])
async def search_messages(request: SearchRequest):
    """搜索包含指定关键词的消息"""
    return bridge.search_messages(
        keyword=request.keyword,
        chat_id=request.chat_id,
        case_sensitive=request.case_sensitive,
        limit=request.limit
    )


# ==================== 兼容Telegram官方API接口 ====================
@app.api_route("/bot{token}/{method}", methods=["GET", "POST"], summary="兼容Telegram官方API格式")
async def telegram_compatible_api(token: str, method: str, request: Request):
    """
    100% 兼容Telegram官方API格式，其他应用无需修改代码，仅替换域名即可使用
    官方格式: https://api.telegram.org/bot<token>/<method>
    替换为: http://你的服务地址/bot<token>/<method>
    """
    # 解析请求参数，兼容query参数、form-data、JSON
    if request.method == "GET":
        params = dict(request.query_params)
    else:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            params = await request.json()
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            params = await request.form()
            params = dict(params)
        else:
            params = {}
    
    # 转换参数类型
    if "chat_id" in params:
        try:
            params["chat_id"] = int(params["chat_id"])
        except:
            pass
    if "disable_notification" in params:
        params["disable_notification"] = str(params["disable_notification"]).lower() in ["true", "1", "yes"]
    
    # 支持的方法映射
    supported_methods = {
        "sendmessage": "text",
        "sendphoto": "photo",
        "senddocument": "document",
        "sendvideo": "video",
        "sendaudio": "audio",
        "sendvoice": "voice"
    }
    
    method_lower = method.lower()
    if method_lower not in supported_methods:
        # 其他方法后续扩展，目前返回不支持
        return {
            "ok": False,
            "error_code": 405,
            "description": f"Method Not Allowed: 暂不支持方法 {method}"
        }
    
    # 处理不同类型的发送
    if supported_methods[method_lower] == "text":
        # 发送文本消息
        required_fields = ["chat_id", "text"]
        for field in required_fields:
            if field not in params:
                return {
                    "ok": False,
                    "error_code": 400,
                    "description": f"Bad Request: 参数 {field} 是必填项"
                }
        
        # 构造发送任务，使用路径中的token
        task_data = {
            "chat_id": params["chat_id"],
            "text": params["text"],
            "parse_mode": params.get("parse_mode", "Markdown"),
            "disable_notification": params.get("disable_notification", False),
            "bot_token": token  # 使用路径中的Bot Token
        }
        
        # 创建发送任务，这里直接同步等待发送结果（兼容官方同步响应）
        task_id = bridge.send_message(task_data)
        if not task_id:
            return {
                "ok": False,
                "error_code": 500,
                "description": "Internal Server Error: 创建发送任务失败"
            }
        
        # 等待发送完成（最多等待10秒，兼容官方同步响应）
        for _ in range(100):
            task = bridge.get_task_status(task_id)
            if task and task["status"] == "success":
                # 返回和官方完全一致的响应格式
                return {
                    "ok": True,
                    "result": {
                        "message_id": task["message_id"],
                        "chat": {
                            "id": task["chat_id"],
                            "type": "private"
                        },
                        "date": int(task["updated_at"]),
                        "text": params["text"]
                    }
                }
            elif task and task["status"] == "failed":
                return {
                    "ok": False,
                    "error_code": 400,
                    "description": task["error_msg"]
                }
            await asyncio.sleep(0.1)
        
        # 超时
        return {
            "ok": False,
            "error_code": 504,
            "description": "Gateway Timeout: 发送超时"
        }
    else:
        # 发送媒体消息
        media_type = supported_methods[method_lower]
        required_fields = ["chat_id"]
        for field in required_fields:
            if field not in params:
                return {
                    "ok": False,
                    "error_code": 400,
                    "description": f"Bad Request: 参数 {field} 是必填项"
                }
        
        # 获取媒体文件：支持file_id、URL或者上传的文件
        media = params.get(media_type)
        if not media:
            return {
                "ok": False,
                "error_code": 400,
                "description": f"Bad Request: 参数 {media_type} 是必填项（文件、file_id或URL）"
            }
        
        # 处理上传的文件对象（FastAPI UploadFile）
        if hasattr(media, "read") and asyncio.iscoroutinefunction(media.read):
            # 是异步文件对象，读取内容
            media = await media.read()
        
        # 校验媒体大小，仅对直接上传的二进制内容校验
        if MAX_MEDIA_SIZE > 0 and isinstance(media, bytes) and len(media) > MAX_MEDIA_SIZE:
            return {
                "ok": False,
                "error_code": 413,
                "description": f"Payload Too Large: 媒体文件大小超出限制，最大允许 {MAX_MEDIA_SIZE//1024//1024} MB"
            }
        
        # 构造媒体发送任务
        task_data = {
            "chat_id": params["chat_id"],
            "media_type": media_type,
            "media": media,
            "caption": params.get("caption", ""),
            "parse_mode": params.get("parse_mode", "Markdown"),
            "disable_notification": params.get("disable_notification", False),
            "bot_token": token  # 使用路径中的Bot Token
        }
        
        # 创建发送任务，同步等待结果
        task_id = bridge.send_message(task_data)
        if not task_id:
            return {
                "ok": False,
                "error_code": 500,
                "description": "Internal Server Error: 创建发送任务失败"
            }
        
        # 等待发送完成（最多等待30秒，媒体文件可能比较大）
        for _ in range(300):
            task = bridge.get_task_status(task_id)
            if task and task["status"] == "success":
                # 返回和官方完全一致的响应格式
                return {
                    "ok": True,
                    "result": {
                        "message_id": task["message_id"],
                        "chat": {
                            "id": task["chat_id"],
                            "type": "private"
                        },
                        "date": int(task["updated_at"]),
                        "caption": params.get("caption", "")
                    }
                }
            elif task and task["status"] == "failed":
                return {
                    "ok": False,
                    "error_code": 400,
                    "description": task["error_msg"]
                }
            await asyncio.sleep(0.1)
        
        # 超时
        return {
            "ok": False,
            "error_code": 504,
            "description": "Gateway Timeout: 媒体发送超时"
        }


# ==================== 服务生命周期 ====================
async def start_bridge_service():
    """启动桥接服务后台任务"""
    asyncio.create_task(bridge.start())


@app.on_event("startup")
async def startup_event():
    """服务启动事件"""
    await start_bridge_service()
    logger.info("✅ API服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """服务停止事件"""
    await bridge.stop()
    logger.info("👋 API服务已停止")


def run_server():
    """启动API服务器"""
    import platform
    host = api_config.get('host', '0.0.0.0')
    port = api_config.get('port', 8080)
    debug = api_config.get('debug', False)
    
    logger.info(f"🚀 启动API服务: http://{host}:{port}")
    logger.info(f"📚 接口文档地址: http://{host}:{port}/docs")
    
    # 优化配置：调试模式下保持默认，生产模式下开启所有优化
    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "reload": debug,
        "log_level": "info" if debug else "warning",
    }
    
    if not debug:
        # 生产环境优化参数，极致内存压缩
        production_kwargs = {
            "workers": 1,  # 必须单进程，避免多进程内存开销
            "limit_concurrency": 50,  # 限制并发数，防止内存暴涨
            "access_log": False,  # 关闭访问日志，减少IO和内存占用
            "server_header": False,  # 关闭Server响应头
            "date_header": False,  # 关闭Date响应头
            "limit_max_requests": 10000,  # 每处理10000个请求自动重启，避免内存泄漏
            "timeout_keep_alive": 5,  # 减少空闲连接超时时间，尽快释放资源
            "backlog": 128,  # 限制TCP连接队列长度，减少内存占用
            "use_colors": False,  # 关闭日志颜色，减少开销
        }
        
        # Windows平台不支持uvloop和httptools，仅Linux/macOS下使用
        if platform.system() != 'Windows':
            production_kwargs.update({
                "loop": "uvloop",  # 使用更快的uvloop事件循环
                "http": "httptools",  # 使用更快的httptools解析HTTP
            })
        
        uvicorn_kwargs.update(production_kwargs)
    
    uvicorn.run(
        "src.api_server:app",
        **uvicorn_kwargs
    )
