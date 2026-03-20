#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bridge Service - 启动入口
集消息监听、存储、中转发送、API服务于一体的完整Telegram桥接服务
"""
import argparse
from loguru import logger
from src.api_server import run_server


def main():
    parser = argparse.ArgumentParser(description="Telegram Bridge Service")
    parser.add_argument('--config', '-c', default='config.yaml', help='配置文件路径')
    args = parser.parse_args()
    
    logger.info(f"📄 使用配置文件: {args.config}")
    run_server()


if __name__ == "__main__":
    main()
