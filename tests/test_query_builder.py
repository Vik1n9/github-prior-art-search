from scripts.search_github import build_queries

FULL_INPUT = {
    "project_goal": "API 速率限制中介層",
    "core_features": ["滑動視窗限流", "多租戶配額"],
    "tech_stack": ["Go", "Redis"],
    "domain": "rate_limiting",
    "extra_keywords": ["rate limiter middleware", "sliding window rate limit",
                       "topic:rate-limiting"],
}


class TestKeywordDrivenQueries:
    def test_queries_are_the_extra_keywords(self):
        queries, warnings = build_queries(FULL_INPUT)
        assert queries == FULL_INPUT["extra_keywords"]
        assert warnings == []

    def test_order_is_preserved(self):
        queries, _ = build_queries(FULL_INPUT)
        assert queries[0] == "rate limiter middleware"

    def test_duplicates_removed_case_insensitively(self):
        queries, _ = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "extra_keywords": ["Rate Limiter", "rate limiter", "  rate   limiter  "],
        })
        assert queries == ["Rate Limiter"]

    def test_whitespace_normalized(self):
        queries, _ = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "extra_keywords": ["  sliding   window\trate  limit "],
        })
        assert queries == ["sliding window rate limit"]

    def test_blank_keywords_dropped(self):
        queries, _ = build_queries({
            "project_goal": "fallback goal",
            "core_features": ["y"],
            "extra_keywords": ["", "   ", "real keyword"],
        })
        assert queries == ["real keyword"]

    def test_capped_by_max_queries(self):
        queries, _ = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "extra_keywords": [f"keyword {n}" for n in range(25)],
        })
        assert len(queries) == 10


class TestProjectGoalFallback:
    def test_falls_back_to_project_goal(self):
        queries, warnings = build_queries({
            "project_goal": "API 速率限制中介層",
            "core_features": ["滑動視窗限流"],
        })
        assert queries == ["API 速率限制中介層"]
        assert [w["type"] for w in warnings] == ["no_extra_keywords"]

    def test_fallback_not_used_when_keywords_present(self):
        queries, warnings = build_queries({
            "project_goal": "API 速率限制中介層",
            "core_features": ["滑動視窗限流"],
            "extra_keywords": ["rate limiter middleware"],
        })
        assert "API 速率限制中介層" not in queries
        assert warnings == []

    def test_degraded_run_is_reported_as_partial(self):
        from main import PARTIAL_WARNING_TYPES
        assert "no_extra_keywords" in PARTIAL_WARNING_TYPES

    def test_empty_keywords_list_triggers_fallback(self):
        queries, warnings = build_queries({
            "project_goal": "rate limiter",
            "core_features": ["y"],
            "extra_keywords": [],
        })
        assert queries == ["rate limiter"]
        assert warnings
