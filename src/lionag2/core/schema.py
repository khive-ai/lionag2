"""FuzzySchema — AG2 ResponseProto with fuzzy JSON parsing + key matching.

Drop-in replacement for PromptedSchema. Injects JSON schema into the system
prompt (bypassing OpenAI strict mode), then validates responses with:
1. Direct Pydantic parse
2. Fuzzy JSON repair (backslash escapes, quotes, brackets)
3. Fuzzy key matching (rapidfuzz Jaro-Winkler)
4. Pydantic model_validate
"""

from typing import TYPE_CHECKING

from autogen.beta.response.prompted import PromptedSchema
from autogen.beta.response.proto import ResponseProto
from pydantic import BaseModel

from .utils import FuzzyUtils

if TYPE_CHECKING:
    from fast_depends import Provider

    from autogen.beta.annotations import Context

from typing import TypeVar

T = TypeVar("T", bound=BaseModel)


class FuzzySchema(ResponseProto[T]):
    """PromptedSchema + fuzzy JSON parsing + fuzzy key matching."""

    def __init__(
        self,
        model_type: type[T],
        /,
        *,
        similarity_threshold: float = 0.82,
    ) -> None:
        self._inner = PromptedSchema(model_type)
        self._model_type = model_type
        self._threshold = similarity_threshold

        self.name = self._inner.name
        self.description = self._inner.description
        self.json_schema = None
        self.system_prompt = self._inner.system_prompt

    async def validate(
        self,
        response: str,
        context: "Context",
        provider: "Provider | None" = None,
    ) -> T:
        # Fast path: standard PromptedSchema validation
        try:
            return await self._inner.validate(response, context, provider)
        except Exception:
            pass

        # Fuzzy path: parse JSON → match keys → validate model
        return FuzzyUtils.fuzzy_validate(response, self._model_type, threshold=self._threshold)
