#!/usr/bin/env python3
"""
诊断作息任务丢失问题的脚本
运行: python backend/diagnose_schedule_loss.py
"""
import json
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.api_public import (
    _has_task_details,
    _normalize_remote_task,
    DATA_STORE,
    _store_get,
    _read_json_optional,
    SCHEDULES_PATH,
)


def diagnose():
    print("=" * 60)
    print("作息任务丢失问题诊断")
    print("=" * 60)
    
    # 1. 检查本地文件
    print("\n1. 检查本地数据文件:")
    if SCHEDULES_PATH.exists():
        data = _read_json_optional(SCHEDULES_PATH)
        if data:
            schedules = data.get("schedules", [])
            print(f"   - 文件存在: {SCHEDULES_PATH}")
            print(f"   - 方案数量: {len(schedules)}")
            for sch in schedules:
                name = sch.get("schedule_name", "未知")
                tasks = sch.get("tasks", [])
                print(f"     • {name}: {len(tasks)} 个任务")
                # 检查前3个任务的详情
                for i, task in enumerate(tasks[:3]):
                    has_details = _has_task_details(task)
                    print(f"       - 任务{i+1}: {task.get('taskname', 'N/A')} | "
                          f"starttime={task.get('starttime', 'N/A')} | "
                          f"has_details={has_details}")
        else:
            print("   - 文件存在但无法解析")
    else:
        print(f"   - 文件不存在: {SCHEDULES_PATH}")
    
    # 2. 检查 _has_task_details 的判断逻辑
    print("\n2. 测试 _has_task_details 函数:")
    test_tasks = [
        {"taskname": "早操", "starttime": "08:00:00"},
        {"name": "眼保健操", "time": "10:00:00"},  # 使用 'time' 而不是 'starttime'
        {"start_time": "14:00:00"},  # 只有时间，没有名称
        {},  # 空任务
        {"starttime": "", "taskname": ""},  # 空字符串
    ]
    for task in test_tasks:
        result = _has_task_details(task)
        print(f"   - {task} => {result}")
    
    # 3. 检查 _normalize_remote_task 的字段映射
    print("\n3. 测试 _normalize_remote_task 函数:")
    raw_tasks = [
        {"name": "广播体操", "time": "09:00:00", "mediaid": "123"},
        {"taskname": "升旗仪式", "start_time": "07:30:00"},
        {"title": "课间音乐", "stime": "10:30:00"},
    ]
    for raw in raw_tasks:
        normalized = _normalize_remote_task(raw)
        has_details = _has_task_details(normalized)
        print(f"   - 原始: {raw}")
        print(f"     规范化: taskname={normalized.get('taskname')}, "
              f"starttime={normalized.get('starttime')}, "
              f"has_details={has_details}")
    
    print("\n" + "=" * 60)
    print("诊断建议:")
    print("=" * 60)
    print("""
如果任务数量显示为0，可能的原因:

1. _has_task_details 过滤过于严格
   - 任务只有时间没有名称会被过滤
   - 任务字段名不匹配（如远端用 'time' 而不是 'starttime'）

2. 本地缓存数据为空
   - 检查文件内容是否确实没有任务
   - 可能需要调用 /admin/sync_data 强制从远端同步

3. 远端返回数据格式问题
   - 检查远端 API 返回的字段名是否与代码期望的一致

快速修复:
- 访问 POST /admin/sync_data 强制同步远端数据
- 或者重启服务触发 _init_data_store 重新加载
""")


if __name__ == "__main__":
    diagnose()
