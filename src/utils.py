#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具模块
"""
import asyncio
from typing import Callable, Any, TypeVar
from loguru import logger

T = TypeVar('T')


async def async_retry(
    func: Callable[..., T],
    max_retries: int,
    retry_interval: int,
    retry_on_exceptions: tuple = (Exception,),
    retry_on_strings: tuple = ("NetworkError", "ConnectError", "Connection refused", "timeout"),
    *args, **kwargs
) -> T:
    """
    通用异步重试函数
    :param func: 要执行的异步函数
    :param max_retries: 最大重试次数
    :param retry_interval: 重试间隔（秒）
    :param retry_on_exceptions: 捕获的异常类型，默认所有异常
    :param retry_on_strings: 异常信息中包含这些字符串时才重试
    :param args: 传递给func的参数
    :param kwargs: 传递给func的关键字参数
    :return: func的返回值
    """
    for retry in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except retry_on_exceptions as e:
            error = str(e)
            # 判断是否符合重试条件
            should_retry = any(s in error for s in retry_on_strings) if retry_on_strings else True
            
            if not should_retry:
                # 非指定异常，直接抛出
                logger.error(f"❌ 非重试类型异常: {error}")
                raise
            
            logger.warning(f"⚠️ 执行失败（第{retry+1}/{max_retries}次）: {error}")
            if retry < max_retries - 1:
                logger.info(f"⏳ {retry_interval}秒后重试...")
                await asyncio.sleep(retry_interval)
            else:
                logger.error(f"💥 已达最大重试次数 {max_retries} 次，执行失败")
                raise
