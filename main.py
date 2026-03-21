#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bridge Service - 启动入口
集消息监听、存储、中转发送、API服务于一体的完整Telegram桥接服务
"""
import os
import argparse
from loguru import logger

# 日志配置：同时输出到终端和文件（必须放在业务模块导入之前，捕获导入错误）
os.makedirs("logs", exist_ok=True)
# 清除默认的终端输出配置
logger.remove()
# 添加终端输出
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
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
    enqueue=True       # 异步写入，避免阻塞
)

from src.api_server import run_server


def main():
    parser = argparse.ArgumentParser(description="Telegram Bridge Service")
    parser.add_argument('--config', '-c', default='config.yaml', help='配置文件路径')
    args = parser.parse_args()
    
    logger.info(f"📄 使用配置文件: {args.config}")
    run_server()


if __name__ == "__main__":
    main()
