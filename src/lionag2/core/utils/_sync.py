import asyncio
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from functools import wraps
from typing import Any, Generic, TypeVar, overload
from uuid import UUID, uuid4

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
        return threading.Lock()
    
    @staticmethod
    def alock():
        return asyncio.Lock()
