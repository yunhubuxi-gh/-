"""
OCR 进程池（ProcessPoolExecutor 真正并发）

背景：
    PaddleOCR 底层是 C++ 预测器（PaddleX），**非线程安全**——单进程内多线程并发调用
    同一实例的 predict() 会触发 C++ vector 越界（invalid vector<bool> subscript）甚至段错误。
    因此「多线程并发」这条路走不通，真正加速只能靠**多进程**：每个子进程独立加载一个
    PaddleOCR 实例，进程间内存隔离，互不影响。

设计：
    - 惰性创建常驻进程池：首次需要并发 OCR 时才创建，之后跨多次文档上传复用，
      避免每次上传都重新加载模型（模型加载比 OCR 本身还慢）。
    - 每个 worker 进程通过 initializer 加载 PaddleOCR（进程级单例）。
    - 单张图片 OCR 失败只返回空串，绝不拖垮整体。
    - 进程池创建失败 / 执行异常 → 自动降级为串行 OCR（锁保护），保证功能可用、不崩溃。

注意：
    - Windows 下 spawn 会重新 import 主模块，需主模块入口有 `if __name__ == "__main__"` 保护；
      uvicorn 以 `python -m uvicorn api.main:app` 启动时该保护天然存在，安全。
    - 多进程内存开销高于多线程：每个子进程一份 PaddleOCR（约数百 MB），max_workers 钳制到 1~4。
"""
from __future__ import annotations

from typing import List, Optional, Callable

from utils.logger import get_logger

logger = get_logger(__name__)

# 进程级 OCR 引擎（每个 worker 子进程独立一份，不在主进程共享）
_worker_engine = None


def _init_worker() -> None:
    """进程池 worker 初始化：加载 PaddleOCR（每个子进程一个实例）"""
    global _worker_engine
    try:
        from utils.ocr_engine import get_ocr_engine
        _worker_engine = get_ocr_engine()
        if _worker_engine is None:
            logger.warning("OCR worker 进程初始化：OCR 引擎不可用（可能未启用或初始化失败）")
    except Exception as e:
        logger.warning(f"OCR worker 进程初始化失败: {e}")
        _worker_engine = None


def _ocr_bytes_worker(image_bytes: bytes) -> str:
    """worker 函数（子进程执行）：对单张图片 OCR，返回文本；失败返回空串"""
    global _worker_engine
    if _worker_engine is None:
        _init_worker()
    if _worker_engine is None:
        return ""
    try:
        return _worker_engine.recognize_image_bytes(image_bytes) or ""
    except Exception as e:
        logger.warning(f"OCR worker 识别失败（跳过该图）: {e}")
        return ""


# ==================== 进程池管理（主进程单例） ====================
_pool = None
_pool_failed = False


def _resolve_max_workers(max_workers: int) -> int:
    """进程数钳制：进程比线程更耗内存，上限 4，避免内存爆炸"""
    try:
        w = int(max_workers or 0)
    except (TypeError, ValueError):
        w = 0
    return max(1, min(w if w > 0 else 4, 4))


def _get_pool(max_workers: int):
    """惰性获取常驻进程池；创建失败返回 None（调用方降级串行）"""
    global _pool, _pool_failed
    if _pool is not None:
        return _pool
    if _pool_failed:
        return None
    try:
        from concurrent.futures import ProcessPoolExecutor
        workers = _resolve_max_workers(max_workers)
        _pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
        )
        logger.info(f"OCR 进程池已创建: max_workers={workers}（每个子进程独立加载 PaddleOCR）")
        return _pool
    except Exception as e:
        _pool_failed = True
        logger.warning(f"OCR 进程池创建失败，回退串行 OCR（不影响功能）: {e}")
        return None


def _safe_cb(callback: Optional[Callable[[int, int], None]], done: int, total: int) -> None:
    if callback is None:
        return
    try:
        callback(done, total)
    except Exception:
        pass


def _ocr_serial(image_bytes_list: List[bytes], progress_callback=None) -> List[str]:
    """串行 OCR 降级路径：复用进程内单例（ocr_engine 内部锁保护 predict，不崩溃）"""
    from utils.ocr_engine import get_ocr_engine
    engine = get_ocr_engine()
    results: List[str] = []
    if engine is None:
        return ["" for _ in image_bytes_list]
    for i, b in enumerate(image_bytes_list):
        try:
            results.append(engine.recognize_image_bytes(b) or "")
        except Exception:
            results.append("")
        _safe_cb(progress_callback, i + 1, len(image_bytes_list))
    return results


def ocr_images_concurrent(
    image_bytes_list: List[bytes],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    max_workers: int = 4,
) -> List[str]:
    """
    并发 OCR 一批图片，返回与输入同序的文本列表（单张失败仅该张为空串）。

    Args:
        image_bytes_list: 图片字节列表
        progress_callback: 进度回调 (done, total)，每完成一张调用一次（主进程单线程触发）
        max_workers: 期望并发进程数（最终钳制到 1~4）

    Returns:
        与输入同序的 OCR 文本列表；进程池不可用时降级为串行（锁保护），功能不受影响。
    """
    n = len(image_bytes_list)
    if n == 0:
        return []
    if n == 1:
        # 单张无需开进程池
        return _ocr_serial(image_bytes_list, progress_callback)

    pool = _get_pool(max_workers)
    if pool is None:
        return _ocr_serial(image_bytes_list, progress_callback)

    from concurrent.futures import as_completed

    results: List[str] = [""] * n
    done = 0
    try:
        futures = {
            pool.submit(_ocr_bytes_worker, b): i
            for i, b in enumerate(image_bytes_list)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result(timeout=120)
            except Exception:
                # 单张失败 / 超时：该张置空，不拖垮整体
                results[i] = ""
            done += 1
            _safe_cb(progress_callback, done, n)
    except Exception as e:
        # 进程池整体异常（极罕见）：已完成的保留，未完成的串行补跑，保证不丢数据
        logger.warning(f"OCR 进程池执行异常，未完成图片串行补跑: {e}")
        for i in range(n):
            if results[i] == "" and image_bytes_list[i]:
                try:
                    results[i] = _ocr_bytes_worker(image_bytes_list[i])
                except Exception:
                    results[i] = ""
    return results
