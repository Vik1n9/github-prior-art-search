import pytest

from scripts.common import ScriptFailure
from scripts.search_github import build_queries, validate_input

FULL_INPUT = {
    "search_queries": ["rate limiter middleware", "sliding window rate limit",
                       "topic:rate-limiting"],
    "project_goal": "API 速率限制中介層",
    "core_features": ["滑動視窗限流", "多租戶配額"],
    "tech_stack": ["Go", "Redis"],
    "domain": "rate_limiting",
}


class TestQueriesComeFromTheCaller:
    def test_queries_are_used_verbatim(self):
        queries, warnings = build_queries(FULL_INPUT)
        assert queries == FULL_INPUT["search_queries"]
        assert warnings == []

    def test_order_is_preserved(self):
        queries, _ = build_queries(FULL_INPUT)
        assert queries[0] == "rate limiter middleware"

    def test_script_never_invents_a_query(self):
        queries, _ = build_queries({
            "project_goal": "API 速率限制中介層",
            "core_features": ["滑動視窗限流"],
            "domain": "rate_limiting",
            "tech_stack": ["Go"],
            "search_queries": ["token bucket go"],
        })
        assert queries == ["token bucket go"]

    def test_duplicates_removed_case_insensitively(self):
        queries, _ = build_queries({
            "search_queries": ["Rate Limiter", "rate limiter", "  rate   limiter  "],
        })
        assert queries == ["Rate Limiter"]

    def test_whitespace_normalized(self):
        queries, _ = build_queries({
            "search_queries": ["  sliding   window\trate  limit "],
        })
        assert queries == ["sliding window rate limit"]

    def test_blank_entries_dropped(self):
        queries, _ = build_queries({"search_queries": ["", "   ", "real query"]})
        assert queries == ["real query"]


class TestTruncationIsReported:
    def test_over_cap_is_truncated_with_a_warning(self):
        queries, warnings = build_queries({
            "search_queries": [f"query {n}" for n in range(25)],
        })
        assert len(queries) == 10
        assert [w["type"] for w in warnings] == ["search_queries_truncated"]
        assert "25" in warnings[0]["detail"]

    def test_at_cap_is_not_a_warning(self):
        queries, warnings = build_queries({
            "search_queries": [f"query {n}" for n in range(10)],
        })
        assert len(queries) == 10
        assert warnings == []

    def test_truncation_marks_the_run_partial(self):
        from main import PARTIAL_WARNING_TYPES
        assert "search_queries_truncated" in PARTIAL_WARNING_TYPES


class TestSearchQueriesIsRequired:
    def test_missing_search_queries_rejected(self):
        with pytest.raises(ScriptFailure) as exc:
            validate_input({"project_goal": "x", "core_features": ["y"]})
        assert "search_queries" in str(exc.value)

    def test_empty_list_rejected(self):
        with pytest.raises(ScriptFailure) as exc:
            validate_input({"project_goal": "x", "core_features": ["y"],
                            "search_queries": []})
        assert "search_queries" in str(exc.value)

    def test_all_blank_strings_rejected(self):
        with pytest.raises(ScriptFailure) as exc:
            validate_input({"project_goal": "x", "core_features": ["y"],
                            "search_queries": ["", "   "]})
        assert "腳本不代為生成" in str(exc.value)

    def test_non_string_entries_rejected(self):
        with pytest.raises(ScriptFailure) as exc:
            validate_input({"project_goal": "x", "core_features": ["y"],
                            "search_queries": ["ok", 42]})
        assert "search_queries" in str(exc.value)

    def test_valid_input_accepted(self):
        assert validate_input(FULL_INPUT) == FULL_INPUT
