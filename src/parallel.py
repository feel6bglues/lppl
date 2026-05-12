# -*- coding: utf-8 -*-
"""
并行计算工具模块
===============
所有策略验证脚本共用，统一管理进程池配置。

关键优化:
1. max_workers = cpu_count - 2 (充分利用32线程，保留2个给系统)
2. worker_init() 缓存模块导入，避免冷启动
3. chunksize 批量提交减少进程间通信开销
4. get_memory_safe_workers() 内存安全阀
"""

import multiprocessing
import os

import psutil

_worker_dm = None
_worker_loaded = False


def get_optimal_workers(reserve: int = 2) -> int:
    """获取最优worker数量 = 全部逻辑核心 - 保留核心"""
    cpu_count = os.cpu_count() or multiprocessing.cpu_count()
    return max(1, cpu_count - reserve)


def get_memory_safe_workers(per_worker_mb: int = 200, reserve_mb: int = 500) -> int:
    """
    基于内存的worker限制（安全阀）
    在最优CPU worker数和内存限制中取较小值
    """
    cpu_workers = get_optimal_workers()
    memory = psutil.virtual_memory()
    available_mb = memory.available / (1024 * 1024)
    mem_workers = max(1, int((available_mb - reserve_mb) / per_worker_mb))
    return min(cpu_workers, mem_workers)


def worker_init():
    """
    进程池初始化函数 (在fork/spawn后执行一次)
    预加载DataManager和pandas/numpy，避免每个任务重复import
    
    用法:
        with ProcessPoolExecutor(max_workers=N, initializer=worker_init) as executor:
            ...
    """
    global _worker_dm, _worker_loaded
    if _worker_loaded:
        return
    # 预加载pandas/numpy（耗时大户）
    # 预加载DataManager（会顺带加载tdx_reader）
    from src.data.manager import DataManager
    _worker_dm = DataManager()
    _worker_loaded = True


def get_worker_dm():
    """获取缓存的DataManager实例（在worker_init后调用）"""
    global _worker_dm
    if _worker_dm is None:
        worker_init()
    return _worker_dm
