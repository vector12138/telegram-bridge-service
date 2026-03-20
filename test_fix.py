#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的bool类型问题
"""
import yaml
from src.redis_manager import get_redis_manager

# 加载配置
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 获取redis管理器
redis_mgr = get_redis_manager(config.get('redis', {}))

# 测试创建发送任务，包含bool类型的disable_notification
test_task = {
    "chat_id": 123456789,
    "text": "测试消息",
    "parse_mode": "Markdown",
    "disable_notification": True
}

print("正在测试创建发送任务...")
task_id = redis_mgr.create_send_task(test_task)
if task_id:
    print(f"✅ 任务创建成功，ID: {task_id}")
    
    # 查询任务状态
    task = redis_mgr.get_task_status(task_id)
    print(f"✅ 查询任务成功，disable_notification字段类型: {type(task['disable_notification'])}, 值: {task['disable_notification']}")
    
    # 删除测试任务
    redis_mgr.client.delete(f"{redis_mgr.prefix}task:{task_id}")
    print("✅ 测试完成，无bool类型错误！")
else:
    print("❌ 任务创建失败")
