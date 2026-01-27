from __future__ import annotations

import logging
import sys
import threading
import time
from functools import wraps
from typing import Callable, NoReturn, TypeVar

from typing_extensions import ParamSpec

T = TypeVar("T")
RT = TypeVar("RT")
P = ParamSpec("P")

LOGGING_FORMAT = (
    "[%(asctime)s][%(levelname)s]-%(name)s:%(funcName)s:%(lineno)d,%(message)s"
)

logger = logging.getLogger()  # use root logger here


def configure_logging(log_level):
    logging.basicConfig(level=logging.CRITICAL, format=LOGGING_FORMAT, force=True)
    _tool_logger = logging.getLogger("ota_image_tools")
    _tool_logger.setLevel(log_level)
    _libs_logger = logging.getLogger("ota_image_libs")
    _libs_logger.setLevel(log_level)


def exit_with_err_msg(err_msg: str, exit_code: int = 1) -> NoReturn:
    print(f"ERR: {err_msg}", file=sys.stderr)
    sys.exit(exit_code)


def func_call_with_se(
    _func: Callable[P, RT], se: threading.Semaphore
) -> Callable[P, RT]:
    @wraps(_func)
    def _wrapped(*args, **kwargs) -> RT:
        se.acquire()
        return _func(*args, **kwargs)

    return _wrapped


def measure_timecost(_func: Callable[P, RT]) -> Callable[P, RT]:
    """Measure the time cost for a function running."""

    @wraps(_func)
    def _wrapped(*args: P.args, **kwargs: P.kwargs) -> RT:
        _start_time = time.perf_counter()
        _res = _func(*args, **kwargs)
        logger.info(f"total time cost: {time.perf_counter() - _start_time}s")
        return _res

    return _wrapped
