import contextlib
from typing import Any
from uuid import UUID, uuid4


class IDUtils:
    @staticmethod
    def get_id(value: Any, suppress: bool = False) -> UUID | None:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            if suppress:
                with contextlib.suppress(ValueError):
                    return UUID(value)
                return None
            return UUID(value)
        lion_id = getattr(value, "lion_id", None)
        if isinstance(lion_id, UUID):
            return lion_id
        if suppress:
            return None
        raise TypeError(f"No lion_id on {type(value).__name__}")

    @staticmethod
    def is_id(value: Any) -> bool:
        if isinstance(value, UUID):
            return True
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                UUID(value)
                return True
        return False

    @staticmethod
    def ensure_id(event: Any) -> UUID:
        existing = getattr(event, "lion_id", None)
        if isinstance(existing, UUID):
            return existing
        uid = uuid4()
        event.lion_id = uid
        return uid

    @staticmethod
    def type_name(event: Any) -> str:
        cls = type(event)
        return f"{cls.__module__}.{cls.__qualname__}"

    @staticmethod
    def type_name_from_class(cls: type) -> str:
        return f"{cls.__module__}.{cls.__qualname__}"
