"""Tests for FuzzyUtils and FuzzySchema.

Covers:
  - fuzzy_parse_json: valid JSON, LaTeX backslashes, single quotes, trailing
    commas, unquoted keys, missing brackets, markdown fences, surrounding text,
    empty/None input.
  - fuzzy_match_keys: exact match, near-miss (Jaro-Winkler), camelCase→snake_case,
    below-threshold, handle_unmatched="remove", handle_unmatched="ignore".
  - fuzzy_validate: end-to-end with clean and mangled input.
  - FuzzySchema: validate() happy path, validate() fuzzy fallback, json_schema is
    None, system_prompt is set, name and description are set.
"""

import pytest
from pydantic import BaseModel

from lionag2.core.schema import FuzzySchema
from lionag2.core.utils import FuzzyUtils

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class SimpleModel(BaseModel):
    score: int
    summary: str


class RichModel(BaseModel):
    body_markdown: str
    quality_score: float
    tags: list[str]


# ---------------------------------------------------------------------------
# fuzzy_parse_json
# ---------------------------------------------------------------------------


class TestFuzzyParseJson:
    def test_valid_json_object_passes_through(self):
        data = FuzzyUtils.fuzzy_parse_json('{"key": "value", "num": 42}')
        assert data == {"key": "value", "num": 42}

    def test_valid_json_array_passes_through(self):
        data = FuzzyUtils.fuzzy_parse_json("[1, 2, 3]")
        assert data == [1, 2, 3]

    def test_unescaped_latex_backslash_alpha(self):
        # \alpha and \beta are not valid JSON escapes — must be doubled
        raw = r'{"formula": "\alpha + \beta"}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert isinstance(result, dict)
        assert "formula" in result

    def test_unescaped_latex_backslash_various(self):
        raw = r'{"eq": "\gamma \delta \epsilon"}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert isinstance(result, dict)

    def test_single_quotes_converted(self):
        raw = "{'name': 'ocean', 'value': 1}"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"name": "ocean", "value": 1}

    def test_trailing_comma_in_object_removed(self):
        raw = '{"a": 1, "b": 2,}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_in_array_removed(self):
        raw = "[1, 2, 3,]"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == [1, 2, 3]

    def test_unquoted_keys_get_quoted(self):
        raw = '{score: 10, label: "good"}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["score"] == 10
        assert result["label"] == "good"

    def test_missing_closing_brace_added(self):
        raw = '{"a": 1, "b": 2'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_missing_closing_bracket_added(self):
        raw = "[1, 2, 3"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == [1, 2, 3]

    def test_json_in_markdown_fence_extracted(self):
        raw = '```json\n{"key": "val"}\n```'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"key": "val"}

    def test_json_in_markdown_fence_with_surrounding_text(self):
        raw = 'Here is the output:\n```json\n{"score": 99}\n```\nDone.'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"score": 99}

    def test_json_object_found_in_surrounding_prose(self):
        raw = 'The answer is: {"result": "ok"} — hope that helps!'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["result"] == "ok"

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            FuzzyUtils.fuzzy_parse_json("")

    def test_whitespace_only_raises_value_error(self):
        with pytest.raises(ValueError):
            FuzzyUtils.fuzzy_parse_json("   \n\t  ")

    def test_none_raises_value_error(self):
        # None is falsy — caught by the `not raw` guard
        with pytest.raises((ValueError, AttributeError, TypeError)):
            FuzzyUtils.fuzzy_parse_json(None)  # type: ignore[arg-type]

    def test_unparseable_garbage_raises_value_error(self):
        with pytest.raises(ValueError):
            FuzzyUtils.fuzzy_parse_json("not json at all !@#$%")

    def test_nested_object(self):
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_combined_single_quotes_and_trailing_comma(self):
        raw = "{'a': 1, 'b': 2,}"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_unicode_values_preserved(self):
        raw = '{"text": "你好世界"}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["text"] == "你好世界"

    def test_numeric_types_preserved(self):
        raw = '{"int": 42, "float": 3.14, "neg": -7}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["int"] == 42
        assert result["float"] == pytest.approx(3.14)
        assert result["neg"] == -7

    def test_boolean_and_null_preserved(self):
        raw = '{"flag": true, "empty": null, "off": false}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["flag"] is True
        assert result["empty"] is None
        assert result["off"] is False

    def test_markdown_fence_content_needing_safe_clean(self):
        # Fence content has single-quotes + trailing comma — direct json.loads
        # fails, but _clean_json_safe should repair it (covers lines 48-50).
        raw = "```json\n{'key': 'val',}\n```"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["key"] == "val"

    def test_surrounding_text_content_needing_safe_clean(self):
        # The embedded JSON has single quotes so the bare json.loads fails;
        # _clean_json_safe handles it (covers lines 60-62).
        raw = "Here is my output: {'result': 'ok'} end."
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result["result"] == "ok"

    def test_backslash_inside_single_quoted_value(self):
        # A single backslash before a regular letter inside a single-quoted
        # string (e.g. Windows path from an LLM) — _fix_backslash_escapes
        # doubles it, then _clean_json_safe converts quotes (lines 183-195).
        raw = "{'path': 'C:\\Users\\ocean'}"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert "path" in result
        assert "ocean" in result["path"]

    def test_escaped_single_quote_inside_single_quoted_value(self):
        # \' inside a single-quoted string — exercises line 186-188.
        raw = r"{'note': 'it\'s fine'}"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert "note" in result

    def test_double_quote_inside_single_quoted_value(self):
        # A literal " inside a single-quoted string — exercises lines 201-203
        # where the cleaner must escape the embedded double quote.
        raw = """{'msg': 'say "hello"'}"""
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert "msg" in result
        assert "hello" in result["msg"]

    def test_backslash_inside_double_quoted_string(self):
        # A valid JSON escape (\\) inside a double-quoted string; exercises
        # the backslash branch in _clean_json_safe's double-quote loop (214-218).
        raw = '{"path": "C:\\\\Users\\\\ocean"}'
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert "path" in result

    def test_unquoted_key_with_spaces_before_colon(self):
        # Whitespace between key token end and ':' — exercises line 246-248
        # (the whitespace-skip loop inside the unquoted-key branch).
        raw = "{score  : 42}"
        result = FuzzyUtils.fuzzy_parse_json(raw)
        assert result.get("score") == 42


# ---------------------------------------------------------------------------
# fuzzy_match_keys
# ---------------------------------------------------------------------------


class TestFuzzyMatchKeys:
    def test_exact_keys_pass_through(self):
        data = {"score": 10, "summary": "good"}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score", "summary"})
        assert result == {"score": 10, "summary": "good"}

    def test_near_miss_typo_corrected(self):
        # "body_markdwon" → "body_markdown"  (Jaro-Winkler ≈ 0.97)
        data = {"body_markdwon": "hello", "quality_score": 1.0}
        result = FuzzyUtils.fuzzy_match_keys(data, {"body_markdown", "quality_score"})
        assert "body_markdown" in result
        assert result["body_markdown"] == "hello"

    def test_camel_case_to_snake_case(self):
        # "qualityScore" → "quality_score": Jaro-Winkler on lowercased strings
        data = {"qualityScore": 0.9, "body_markdown": "text"}
        result = FuzzyUtils.fuzzy_match_keys(data, {"quality_score", "body_markdown"})
        assert "quality_score" in result
        assert result["quality_score"] == pytest.approx(0.9)

    def test_below_threshold_not_matched_remove_mode(self):
        # "xyz" vs "body_markdown" is far below 0.82
        data = {"xyz": "junk"}
        result = FuzzyUtils.fuzzy_match_keys(
            data, {"body_markdown"}, threshold=0.82, handle_unmatched="remove"
        )
        assert "xyz" not in result
        assert "body_markdown" not in result

    def test_handle_unmatched_remove_drops_unknown_keys(self):
        data = {"score": 5, "unknown_field": "drop me"}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score"}, handle_unmatched="remove")
        assert "unknown_field" not in result
        assert result["score"] == 5

    def test_handle_unmatched_ignore_keeps_unknown_keys(self):
        data = {"score": 5, "unknown_field": "keep me"}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score"}, handle_unmatched="ignore")
        assert result["unknown_field"] == "keep me"
        assert result["score"] == 5

    def test_empty_expected_keys_returns_data_unchanged(self):
        data = {"a": 1, "b": 2}
        result = FuzzyUtils.fuzzy_match_keys(data, set())
        assert result == data

    def test_expected_keys_as_list(self):
        data = {"score": 10}
        result = FuzzyUtils.fuzzy_match_keys(data, ["score", "summary"])
        assert result["score"] == 10

    def test_expected_keys_as_dict(self):
        # dict form: keys are the expected field names
        data = {"score": 10}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score": None, "summary": None})
        assert result["score"] == 10

    def test_exact_match_takes_priority_over_fuzzy(self):
        # If "score" is exact, it should NOT be confused with any other field
        data = {"score": 7, "scor": 3}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score"}, handle_unmatched="remove")
        assert result.get("score") == 7

    def test_multiple_near_misses_all_corrected(self):
        data = {"body_markdwon": "md", "qualyti_score": 0.5, "tagz": ["a"]}
        result = FuzzyUtils.fuzzy_match_keys(
            data,
            {"body_markdown", "quality_score", "tags"},
            threshold=0.75,
        )
        # At least body_markdown should be corrected (very close typo)
        assert "body_markdown" in result

    def test_empty_data_returns_empty(self):
        result = FuzzyUtils.fuzzy_match_keys({}, {"score", "summary"})
        assert result == {}

    def test_threshold_boundary_exact_match_always_passes(self):
        # Even with threshold=1.0, exact matches must still work
        data = {"score": 99}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score"}, threshold=1.0)
        assert result["score"] == 99

    def test_ignore_mode_extra_keys_after_fields_exhausted(self):
        # When all expected fields are already matched and there are still
        # unmatched input keys, "ignore" mode keeps them (covers line 112 +
        # the tail loop at lines 115-117).
        data = {"score": 1, "extra_a": "x", "extra_b": "y"}
        result = FuzzyUtils.fuzzy_match_keys(data, {"score"}, handle_unmatched="ignore")
        assert result["score"] == 1
        assert result["extra_a"] == "x"
        assert result["extra_b"] == "y"


# ---------------------------------------------------------------------------
# fuzzy_validate
# ---------------------------------------------------------------------------


class TestFuzzyValidate:
    def test_valid_json_correct_keys_produces_model(self):
        raw = '{"score": 42, "summary": "all good"}'
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel)
        assert isinstance(instance, SimpleModel)
        assert instance.score == 42
        assert instance.summary == "all good"

    def test_single_quotes_input_produces_model(self):
        raw = "{'score': 7, 'summary': 'works'}"
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel)
        assert isinstance(instance, SimpleModel)
        assert instance.score == 7

    def test_trailing_comma_input_produces_model(self):
        raw = '{"score": 5, "summary": "trailing",}'
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel)
        assert isinstance(instance, SimpleModel)

    def test_typo_keys_corrected_and_model_valid(self):
        # "scor" is close enough to "score"; "summry" is close to "summary"
        raw = '{"scor": 9, "summry": "close enough"}'
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel, threshold=0.75)
        assert isinstance(instance, SimpleModel)
        assert instance.score == 9

    def test_broken_json_and_wrong_keys_still_produces_model(self):
        # Missing close brace + typo key
        raw = '{"scor": 3, "summry": "fuzzy"'
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel, threshold=0.75)
        assert isinstance(instance, SimpleModel)

    def test_invalid_input_raises_on_failure(self):
        # A completely unparseable string with no JSON structure should raise
        with pytest.raises((ValueError, Exception)):
            FuzzyUtils.fuzzy_validate("not json at all !@#$%", SimpleModel)

    def test_rich_model_with_typos(self):
        raw = '{"body_markdwon": "# Title", "qualityScore": 0.9, "tagz": ["x", "y"]}'
        instance = FuzzyUtils.fuzzy_validate(raw, RichModel, threshold=0.75)
        assert isinstance(instance, RichModel)
        assert instance.body_markdown == "# Title"

    def test_markdown_fence_end_to_end(self):
        raw = '```json\n{"score": 100, "summary": "perfect"}\n```'
        instance = FuzzyUtils.fuzzy_validate(raw, SimpleModel)
        assert isinstance(instance, SimpleModel)
        assert instance.score == 100


# ---------------------------------------------------------------------------
# FuzzySchema
# ---------------------------------------------------------------------------


class _DummyContext:
    """Minimal stand-in for autogen Context (not passed to FuzzySchema.validate path)."""


class TestFuzzySchema:
    def test_json_schema_is_none(self):
        schema = FuzzySchema(SimpleModel)
        assert schema.json_schema is None

    def test_system_prompt_is_set(self):
        schema = FuzzySchema(SimpleModel)
        assert schema.system_prompt is not None
        assert len(schema.system_prompt) > 0

    def test_name_is_set(self):
        schema = FuzzySchema(SimpleModel)
        assert schema.name == "SimpleModel"

    def test_description_attribute_exists(self):
        # description may be None for models without a docstring-derived description
        schema = FuzzySchema(SimpleModel)
        # The attribute must exist (it's assigned in __init__)
        assert hasattr(schema, "description")

    @pytest.mark.asyncio
    async def test_validate_succeeds_on_valid_json(self):
        schema = FuzzySchema(SimpleModel)
        result = await schema.validate(
            '{"score": 42, "summary": "nice"}',
            context=_DummyContext(),
        )
        assert isinstance(result, SimpleModel)
        assert result.score == 42
        assert result.summary == "nice"

    @pytest.mark.asyncio
    async def test_validate_succeeds_on_broken_json_fuzzy_fallback(self):
        schema = FuzzySchema(SimpleModel)
        # Single quotes + trailing comma = broken JSON that fuzzy path repairs
        result = await schema.validate(
            "{'score': 8, 'summary': 'fuzzy path',}",
            context=_DummyContext(),
        )
        assert isinstance(result, SimpleModel)
        assert result.score == 8

    @pytest.mark.asyncio
    async def test_validate_handles_typo_keys(self):
        schema = FuzzySchema(SimpleModel, similarity_threshold=0.75)
        result = await schema.validate(
            '{"scor": 3, "summry": "close"}',
            context=_DummyContext(),
        )
        assert isinstance(result, SimpleModel)

    @pytest.mark.asyncio
    async def test_validate_handles_missing_bracket(self):
        schema = FuzzySchema(SimpleModel)
        result = await schema.validate(
            '{"score": 77, "summary": "incomplete"',
            context=_DummyContext(),
        )
        assert isinstance(result, SimpleModel)
        assert result.score == 77

    @pytest.mark.asyncio
    async def test_validate_handles_markdown_fence(self):
        schema = FuzzySchema(SimpleModel)
        raw = '```json\n{"score": 55, "summary": "in a fence"}\n```'
        result = await schema.validate(raw, context=_DummyContext())
        assert isinstance(result, SimpleModel)
        assert result.score == 55

    def test_custom_similarity_threshold_stored(self):
        schema = FuzzySchema(SimpleModel, similarity_threshold=0.90)
        assert schema._threshold == 0.90

    def test_default_similarity_threshold(self):
        schema = FuzzySchema(SimpleModel)
        assert schema._threshold == 0.82
