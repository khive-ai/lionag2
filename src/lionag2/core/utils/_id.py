import contextlib
from uuid import UUID, uuid4
from typing import Any

def _coerce_to_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise TypeError("Expected UUID or str")


class IDUtils:

    @staticmethod
    def get_id(value: Any, surpress: bool = False) -> UUID | None:
        lion_id = getattr(value, "lion_id", None)
        if isinstance(lion_id, UUID):
            return lion_id
        value = getattr(value, "id", value) if not isinstance(value, (UUID, str)) else value
        if surpress:
            with contextlib.suppress(TypeError, ValueError):
                return _coerce_to_uuid(value)
            return None
        return _coerce_to_uuid(value)

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
        """Ensure an AG2 event has a UUID `.lion_id`. Idempotent.

        Uses `lion_id` instead of `id` because some AG2 events already
        have `.id` with non-UUID values (e.g. ToolCallEvent.id = "call_xxx").
        """
        existing = getattr(event, "lion_id", None)
        if isinstance(existing, UUID):
            return existing
        uid = uuid4()
        event.lion_id = uid
        return uid

    @staticmethod
    def type_name(event: Any) -> str:
        """Fully qualified type name for polymorphic dispatch."""
        cls = type(event)
        return f"{cls.__module__}.{cls.__qualname__}"

    @staticmethod
    def type_name_from_class(cls: type) -> str:
        return f"{cls.__module__}.{cls.__qualname__}"

