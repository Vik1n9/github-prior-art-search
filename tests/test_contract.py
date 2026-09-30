import copy
import json

import pytest

from conftest import SKILL_ROOT, component
from scripts.common import ScriptFailure
from scripts.contract import input_warnings, validate_input


def valid_input(**overrides):
    data = {"requirement": "需求原文", "tech_stack": ["Go"],
            "components": [component("core"), component("store", queries=("q2",))]}
    data.update(overrides)
    return data


def rejected(data):
    with pytest.raises(ScriptFailure) as exc:
        validate_input(data)
    assert exc.value.reason_code == "invalid_input"
    return str(exc.value)


class TestValidInput:
    def test_example_file_is_valid(self):
        data = json.loads((SKILL_ROOT / "input.example.json").read_text(encoding="utf-8"))
        assert validate_input(data) is data

    def test_minimal_input(self):
        assert validate_input(valid_input())


class TestRejections:
    def test_requirement_required(self):
        assert "requirement" in rejected(valid_input(requirement=" "))

    def test_components_required(self):
        assert "不代為拆解" in rejected(valid_input(components=[]))

    @pytest.mark.parametrize("field", ["must_have", "match_terms", "search_queries"])
    def test_component_lists_required(self, field):
        comp = component("core")
        comp[field] = []
        assert field in rejected(valid_input(components=[comp]))

    def test_bad_component_id(self):
        assert ".id" in rejected(valid_input(components=[component("Core ID")]))

    def test_duplicate_component_ids(self):
        assert "不得重複" in rejected(valid_input(
            components=[component("core"), component("core", queries=("x",))]))

    def test_duplicate_queries_case_insensitive(self):
        assert "search_queries 不得重複" in rejected(valid_input(
            components=[component("core", queries=("Rate Limit", "rate  limit"))]))

    def test_duplicate_must_have(self):
        assert "must_have 不得重複" in rejected(valid_input(
            components=[component("core", must_have=("a", "a"))]))

    def test_too_many_queries_per_component(self, config):
        cap = config["search"]["max_queries_per_component"]
        queries = tuple(f"q{i}" for i in range(cap + 1))
        assert "最多" in rejected(valid_input(components=[component("c", queries=queries)]))

    def test_too_many_total_queries(self, config):
        per = config["search"]["max_queries_per_component"]
        count = config["search"]["max_total_queries"] // per + 1
        comps = [component(f"c{i}", queries=tuple(f"q{i}-{j}" for j in range(per)))
                 for i in range(count)]
        message = rejected(valid_input(components=comps))
        assert "合計" in message

    def test_empty_topic_qualifier(self):
        assert "topic:" in rejected(valid_input(
            components=[component("c", queries=("topic: rate-limit",))]))

    def test_star_qualifier_rejected(self):
        assert "stars:" in rejected(valid_input(
            components=[component("c", queries=("limiter stars:>10",))]))

    def test_overlong_query(self, config):
        long_query = "x" * (config["search"]["max_query_length"] + 1)
        assert "超過" in rejected(valid_input(components=[component("c", queries=(long_query,))]))

    @pytest.mark.parametrize("field,value", [
        ("min_stars", 0), ("min_stars", True), ("candidates_per_component", 99),
        ("last_commit_within_days", "30")])
    def test_numeric_fields(self, field, value):
        assert field in rejected(valid_input(**{field: value}))

    def test_all_errors_reported_together(self):
        comp = copy.deepcopy(component("core"))
        comp["must_have"] = []
        comp["match_terms"] = []
        message = rejected(valid_input(requirement="", components=[comp]))
        assert message.count("\n- ") == 3


class TestWarnings:
    def test_cjk_only_match_terms_warned(self):
        data = valid_input(components=[component("c", match_terms=("滑動視窗", "限流"))])
        assert [w["type"] for w in input_warnings(data)] == ["match_terms_cjk_only"]

    def test_mixed_terms_not_warned(self):
        data = valid_input(components=[component("c", match_terms=("滑動視窗", "rate limit"))])
        assert input_warnings(data) == []
