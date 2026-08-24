import json
from pathlib import Path

from scripts.search_github import build_queries

FULL_INPUT = {
    "project_goal": "API 速率限制中介層 rate limiter",
    "core_features": ["滑動視窗限流", "多租戶配額", "Redis 儲存"],
    "tech_stack": ["Go", "Redis"],
    "domain": "rate_limiting",
    "extra_keywords": ["rate limiter middleware", "sliding window redis quota"],
}


class TestTemplateExpansion:
    def test_goal_first_words(self):
        queries = build_queries({
            "project_goal": "api rate limiter middleware",
            "core_features": [],
        })
        assert "api rate limiter" in queries

    def test_domain_templates(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["quota tracking"],
            "domain": "rate_limiting",
        })
        assert "topic:rate limiting" in queries
        assert "rate limiting quota tracking" in queries

    def test_feature_limit(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["alpha beta", "gamma delta", "epsilon zeta", "eta theta"],
        })
        assert "alpha beta" in queries
        assert "gamma delta" in queries
        assert "epsilon zeta" in queries
        assert "eta theta" not in queries

    def test_domain_feature_limit(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["alpha beta", "gamma delta", "epsilon zeta"],
            "domain": "infra",
        })
        assert "infra alpha beta" in queries
        assert "infra gamma delta" in queries
        assert "infra epsilon zeta" not in queries

    def test_stack_feature_cross_product(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["alpha beta"],
            "tech_stack": ["Go", "Rust", "Python"],
        })
        assert "Go alpha beta" in queries
        assert "Rust alpha beta" in queries
        assert "Python alpha beta" not in queries

    def test_stack_domain_uses_first_stack(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "tech_stack": ["Go", "Rust"],
            "domain": "rate_limiting",
        })
        assert "Go rate limiting" in queries
        assert "Rust rate limiting" not in queries

    def test_missing_placeholder_skips_template(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
        })
        assert not any("topic:" in q for q in queries)

    def test_no_duplicates(self):
        queries = build_queries(FULL_INPUT)
        lowered = [q.lower() for q in queries]
        assert len(lowered) == len(set(lowered))

    def test_capped_by_max_queries(self):
        assert len(build_queries(FULL_INPUT)) <= 10


class TestExtraKeywordPriority:
    def test_extra_keywords_come_first(self):
        queries = build_queries(FULL_INPUT)
        assert queries[:2] == FULL_INPUT["extra_keywords"]

    def test_extra_keywords_survive_the_cap(self):
        crowded = dict(FULL_INPUT,
                       core_features=[f"feature {n}" for n in range(12)],
                       tech_stack=["Go", "Rust", "Python"])
        queries = build_queries(crowded)
        assert len(queries) == 10
        for keyword in crowded["extra_keywords"]:
            assert keyword in queries


class TestTemplatesStayDomainNeutral:
    BIASED_TERMS = ("admin dashboard", "management system", "engine",
                    "backend", "cms", "portal")

    def test_no_hardcoded_project_shape(self):
        path = Path(__file__).resolve().parent.parent / "templates" / "queries.json"
        templates = json.loads(path.read_text(encoding="utf-8"))["templates"]
        for item in templates:
            text = item["template"].lower()
            literal = text.replace("{goal_first_words}", "").replace("{domain}", "")
            literal = literal.replace("{feature}", "").replace("{tech_stack}", "")
            for term in self.BIASED_TERMS:
                assert term not in literal, f"模板 {item['template']} 寫死了領域字眼"

    def test_unrelated_project_gets_clean_queries(self):
        queries = build_queries({
            "project_goal": "PDF parsing library",
            "core_features": ["text extraction", "table detection"],
            "tech_stack": ["Rust"],
            "domain": "document_processing",
        })
        for term in self.BIASED_TERMS:
            assert not any(term in q.lower() for q in queries)
