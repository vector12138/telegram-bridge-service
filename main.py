#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bridge Service - 启动入口
集消息监听、存储、中转发送、API服务于一体的完整Telegram桥接服务
"""
import os
import sys
import argparse
import asyncio
import traceback

# 开启最高级别优化，减少内存占用
sys.dont_write_bytecode = True
os.environ['PYTHONOPTIMIZE'] = '2'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONUNBUFFERED'] = '1'

# 日志配置：同时输出到终端和文件（必须放在业务模块导入之前，捕获导入错误）
os.makedirs("logs", exist_ok=True)
import logging
from loguru import logger

# 自定义异常处理器：仅打印最后一行异常信息，无traceback
def custom_exception_handler(type, value, tb):
    error_msg = f"{type.__name__}: {value}"
    logger.error(error_msg)

# 覆盖全局异常处理器
sys.excepthook = custom_exception_handler

# 覆盖asyncio异常处理器
def custom_async_exception_handler(loop, context):
    exception = context.get('exception')
    if exception:
        error_msg = f"{exception.__class__.__name__}: {exception}"
        logger.error(error_msg)
    else:
        logger.error(context.get('message', 'Unknown async error'))

asyncio.get_event_loop_policy().get_event_loop().set_exception_handler(custom_async_exception_handler)

# 拦截标准库logging的所有日志，重定向到loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        # 获取对应的loguru日志级别
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 查找调用栈
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # 异常信息只保留最后一行，不打印栈
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            msg = f"{record.getMessage()} - {exc_type.__name__}: {exc_value}"
            logger.opt(depth=depth).log(level, msg)
        else:
            logger.opt(depth=depth).log(level, record.getMessage())

# 配置根日志处理器
logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
# 手动设置第三方库的日志级别，避免太啰嗦
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# 清除默认的终端输出配置
logger.remove()
# 添加终端输出
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
    backtrace=False,  # 完全关闭调用栈
    diagnose=False,   # 完全关闭诊断信息
    catch=False       # 不自动捕获异常，由我们自己处理
)
# 添加文件输出（按天切割，保留7天日志）
logger.add(
    sink="logs/telegram-bridge.{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",  # 每天0点自动切割
    retention=7,       # 保留最近7天日志
    compression="zip", # 旧日志自动压缩
    encoding="utf-8",
    enqueue=True,      # 异步写入，避免阻塞
    backtrace=True,    # 日志文件保留完整栈便于排查问题
    diagnose=True
)


def main():
    parser = argparse.ArgumentParser(description="Telegram Bridge Service")
    parser.add_argument('--config', '-c', default='config.yaml', help='配置文件路径')
    args = parser.parse_args()
    
    logger.info(f"📄 使用配置文件: {args.config}")
    # 延迟导入业务模块，避免启动时提前加载大依赖
    from src.api_server import run_server
    run_server()


if __name__ == "__main__":
    main()
