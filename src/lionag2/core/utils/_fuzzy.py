"""Fuzzy JSON parsing + key matching — ported from lionagi.

Fixes common LLM JSON issues: unescaped backslashes, single quotes,
trailing commas, unquoted keys, mismatched brackets, markdown fences.
Then fuzzy-matches dict keys to expected Pydantic fields using rapidfuzz.
"""

import json
import re
from typing import Any

from pydantic import BaseModel
from rapidfuzz.distance import JaroWinkler


def _jaro_winkler(a: str, b: str) -> float:
    return JaroWinkler.similarity(a, b)


_JSON_BLOCK_PATTERN = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


class FuzzyUtils:
    @staticmethod
    def fuzzy_parse_json(raw: str) -> dict | list:
        """Parse JSON with progressive fuzzy correction."""
        if not raw or not raw.strip():
            raise ValueError("Empty input")

        for attempt in (_try_direct, _try_fix_escapes, _try_clean_safe, _try_clean_regex):
            result = attempt(raw)
            if result is not None:
                return result

        # Fix brackets on cleaned candidates
        for candidate in (
            _clean_json_safe(_fix_backslash_escapes(raw)),
            _clean_json_regex(_fix_backslash_escapes(raw)),
        ):
            try:
                return json.loads(_fix_brackets(candidate))
            except (json.JSONDecodeError, ValueError):
                pass

        # Extract from markdown fences
        for m in _JSON_BLOCK_PATTERN.findall(raw):
            fixed = _fix_backslash_escapes(m)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                try:
                    return json.loads(_clean_json_safe(fixed))
                except json.JSONDecodeError:
                    continue

        # Last resort: find JSON object boundaries
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            chunk = _fix_backslash_escapes(raw[start:end])
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                try:
                    return json.loads(_clean_json_safe(chunk))
                except json.JSONDecodeError:
                    pass

        raise ValueError("Could not parse JSON after all fuzzy attempts")

    @staticmethod
    def fuzzy_match_keys(
        data: dict[str, Any],
        expected_keys: set[str] | list[str] | dict[str, Any],
        *,
        threshold: float = 0.82,
        handle_unmatched: str = "remove",
    ) -> dict[str, Any]:
        """Match dict keys to expected keys using string similarity.

        LLMs sometimes return 'body_markdwon' instead of 'body_markdown',
        or 'qualityScore' instead of 'quality_score'. This fixes those.
        """
        fields = set(expected_keys) if isinstance(expected_keys, (list, dict)) else expected_keys
        if not fields:
            return data

        out: dict[str, Any] = {}
        matched_fields: set[str] = set()
        matched_input: set[str] = set()

        # Pass 1: exact matches
        for key in data:
            if key in fields:
                out[key] = data[key]
                matched_fields.add(key)
                matched_input.add(key)

        # Pass 2: fuzzy matches on remaining
        remaining_fields = fields - matched_fields
        for key in set(data) - matched_input:
            if not remaining_fields:
                break
            best_score, best_match = 0.0, None
            key_lower = key.lower()
            for field in remaining_fields:
                score = _jaro_winkler(key_lower, field.lower())
                if score > best_score:
                    best_score, best_match = score, field
            if best_match and best_score >= threshold:
                out[best_match] = data[key]
                matched_fields.add(best_match)
                matched_input.add(key)
                remaining_fields.remove(best_match)
            elif handle_unmatched == "ignore":
                out[key] = data[key]

        # Keep unmatched input keys for "ignore" mode
        if handle_unmatched == "ignore":
            for key in set(data) - matched_input:
                out[key] = data[key]

        return out

    @staticmethod
    def fuzzy_validate(raw: str, model_type: type[BaseModel], *, threshold: float = 0.82):
        """Parse raw LLM text → fuzzy JSON → fuzzy key match → Pydantic model.

        Returns validated model instance or raises ValueError.
        """
        data = FuzzyUtils.fuzzy_parse_json(raw)
        if isinstance(data, dict):
            data = FuzzyUtils.fuzzy_match_keys(
                data, set(model_type.model_fields), threshold=threshold
            )
        return model_type.model_validate(data)


def _try_direct(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _try_fix_escapes(raw: str):
    try:
        return json.loads(_fix_backslash_escapes(raw))
    except json.JSONDecodeError:
        return None


def _try_clean_safe(raw: str):
    try:
        return json.loads(_clean_json_safe(_fix_backslash_escapes(raw)))
    except json.JSONDecodeError:
        return None


def _try_clean_regex(raw: str):
    try:
        return json.loads(_clean_json_regex(_fix_backslash_escapes(raw)))
    except json.JSONDecodeError:
        return None


def _fix_backslash_escapes(s: str) -> str:
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", s)


def _clean_json_safe(s: str) -> str:
    """State-machine JSON cleaner."""
    result: list[str] = []
    pos = 0
    length = len(s)

    while pos < length:
        char = s[pos]

        if char == "'":
            result.append('"')
            pos += 1
            while pos < length:
                ic = s[pos]
                if ic == "\\":
                    if pos + 1 < length:
                        nc = s[pos + 1]
                        if nc == "'":
                            result.append("'")
                            pos += 2
                            continue
                        result.append(ic)
                        result.append(nc)
                        pos += 2
                        continue
                    result.append(ic)
                    pos += 1
                    continue
                if ic == "'":
                    result.append('"')
                    pos += 1
                    break
                if ic == '"':
                    result.append('\\"')
                    pos += 1
                    continue
                result.append(ic)
                pos += 1
            continue

        if char == '"':
            result.append(char)
            pos += 1
            while pos < length:
                ic = s[pos]
                if ic == "\\":
                    result.append(ic)
                    if pos + 1 < length:
                        pos += 1
                        result.append(s[pos])
                    pos += 1
                    continue
                result.append(ic)
                if ic == '"':
                    pos += 1
                    break
                pos += 1
            continue

        if char in "{,":
            if char == ",":
                lookahead = pos + 1
                while lookahead < length and s[lookahead] in " \t\n\r":
                    lookahead += 1
                if lookahead < length and s[lookahead] in "]}":
                    pos += 1
                    continue
            result.append(char)
            pos += 1
            while pos < length and s[pos] in " \t\n\r":
                result.append(s[pos])
                pos += 1
            if pos < length and s[pos] not in "\"'{[":
                key_start = pos
                while pos < length and (s[pos].isalnum() or s[pos] == "_"):
                    pos += 1
                if pos < length and key_start < pos:
                    key_end = pos
                    while pos < length and s[pos] in " \t\n\r":
                        pos += 1
                    if pos < length and s[pos] == ":":
                        result.append(f'"{s[key_start:key_end]}"')
                        continue
                    else:
                        pos = key_start
            continue

        result.append(char)
        pos += 1

    return "".join(result).strip()


def _clean_json_regex(s: str) -> str:
    s = re.sub(r"(?<!\\)'", '"', s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r'([{,])\s*([^"\s]+)\s*:', r'\1"\2":', s)
    return s.strip()


def _fix_brackets(s: str) -> str:
    if not s:
        raise ValueError("Empty input")
    brackets = {"{": "}", "[": "]"}
    stack: list[str] = []
    pos = 0
    length = len(s)
    while pos < length:
        c = s[pos]
        if c == "\\":
            pos += 2
            continue
        if c == '"':
            pos += 1
            while pos < length:
                if s[pos] == "\\":
                    pos += 2
                    continue
                if s[pos] == '"':
                    pos += 1
                    break
                pos += 1
            continue
        if c in brackets:
            stack.append(brackets[c])
        elif c in brackets.values():
            if not stack or stack[-1] != c:
                raise ValueError("Mismatched brackets")
            stack.pop()
        pos += 1
    if stack:
        s += "".join(reversed(stack))
    return s
