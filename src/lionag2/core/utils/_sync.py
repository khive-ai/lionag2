import asyncio
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any


class SyncUtils:
    @staticmethod
    def _sync(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(self, *a: Any, **kw: Any) -> Any:
            with self._lock:
                return fn(self, *a, **kw)

        return wrapper

    @staticmethod
    def _async(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(self, *a: Any, **kw: Any) -> Any:
            async with self._alock:
                return await fn(self, *a, **kw)

        return wrapper

    @staticmethod
    def lock():
        return threading.RLock()

    @staticmethod
    def alock():
        return asyncio.Lock()
