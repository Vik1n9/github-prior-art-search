# -*- coding: utf-8 -*-
"""§9 驗收：查詢由 templates/queries.yaml 模板產生（單一事實來源）。"""
from search_github import build_queries


FULL_INPUT = {
    "project_goal": "遊戲活動配置後台 admin panel",
    "core_features": ["活動配置", "任務配置", "獎勵發放", "審核流程"],
    "tech_stack": ["TypeScript", "Node.js"],
    "domain": "game_ops",
    "extra_keywords": ["game ops admin dashboard"],
}


class TestTemplateExpansion:
    def test_goal_first_words(self):
        queries = build_queries({
            "project_goal": "game ops admin panel",
            "core_features": [],
        })
        assert "game ops admin" in queries

    def test_domain_templates(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "domain": "game_ops",
        })
        assert "game ops admin dashboard" in queries
        assert "topic:game ops" in queries

    def test_feature_limit(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["alpha beta", "gamma delta", "epsilon zeta", "eta theta"],
        })
        assert "alpha beta management system" in queries
        assert "gamma delta management system" in queries
        assert "epsilon zeta management system" in queries
        assert "eta theta management system" not in queries
        assert "alpha beta engine" in queries
        assert "gamma delta engine" in queries
        assert "epsilon zeta engine" not in queries

    def test_stack_feature_cross_product(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["alpha beta"],
            "tech_stack": ["TypeScript", "Node.js", "Python"],
        })
        assert "TypeScript alpha beta" in queries
        assert "Node.js alpha beta" in queries
        assert "Python alpha beta" not in queries

    def test_stack_domain_uses_first_stack(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
            "tech_stack": ["TypeScript", "Node.js"],
            "domain": "game_ops",
        })
        assert "TypeScript game ops" in queries
        assert "Node.js game ops" not in queries

    def test_extra_keywords_appended(self):
        queries = build_queries(FULL_INPUT)
        assert "game ops admin dashboard" in queries

    def test_missing_placeholder_skips_template(self):
        queries = build_queries({
            "project_goal": "x",
            "core_features": ["y"],
        })
        for q in queries:
            assert "admin dashboard" not in q
            assert "topic:" not in q

    def test_no_duplicates(self):
        queries = build_queries(FULL_INPUT)
        lowered = [q.lower() for q in queries]
        assert len(lowered) == len(set(lowered))

    def test_capped_by_max_queries(self):
        queries = build_queries(FULL_INPUT)
        assert len(queries) <= 10
