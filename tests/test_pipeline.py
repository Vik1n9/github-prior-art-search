import pytest

from conftest import NOW_TS, component, repo
from scripts.common import ScriptFailure
from scripts.pipeline import run_search

GOOD_TREE = ["go.mod", "go.sum", "limiter.go", "limiter_test.go",
             ".github/workflows/ci.yml", "examples/main.go", "LICENSE"]
GOOD_FILES = {"go.mod": "module x\n\nrequire (\n\tgithub.com/redis/go-redis/v9 v9.0.0\n)\n"}
README = "# Limiter\nSliding window rate limit for Go.\n## Install\ngo get x\n## Usage\n"


def base_input(**overrides):
    data = {
        "requirement": "多租戶 API 限流",
        "tech_stack": ["Go"],
        "components": [
            component("core", queries=("sliding window go", "rate limit go"),
                      match_terms=("sliding window", "rate limit")),
            component("store", queries=("redis rate limit",),
                      match_terms=("redis", "distributed")),
        ],
    }
    data.update(overrides)
    return data


def run(data, config, **kwargs):
    return run_search(data, "token", config, now_ts=NOW_TS, **kwargs)


@pytest.fixture
def github(fake_github):
    fake_github.add_repo(
        repo("acme/limiter", stars=2000, description="Sliding window rate limiter",
             topics=["redis"]),
        ["sliding window go", "rate limit go", "redis rate limit"],
        tree=GOOD_TREE, readme=README, files=GOOD_FILES)
    fake_github.add_repo(
        repo("big/framework", stars=90000, description="Full-stack web framework",
             spdx="AGPL-3.0"),
        ["rate limit go"], tree=["main.go"], readme="A web framework.")
    fake_github.add_repo(repo("tiny/lib", stars=50), ["sliding window go"])
    fake_github.add_repo(repo("old/lib", pushed_days_ago=900), ["rate limit go"])
    return fake_github


class TestSearchPhase:
    def test_relevant_repo_outranks_popular_irrelevant_one(self, github, config):
        result = run(base_input(), config)
        core = result["components"][0]
        assert [c["repository"] for c in core["candidates"]] == [
            "acme/limiter", "big/framework"]
        assert core["candidates"][0]["matched_queries"] == [
            "sliding window go", "rate limit go"]

    def test_hard_filters_applied(self, github, config):
        core = run(base_input(), config)["components"][0]
        reasons = {d["repository"]: d["reason"] for d in core["discarded_sample"]}
        assert reasons == {"tiny/lib": "stars<100", "old/lib": "last_push>730d"}

    def test_shared_repo_is_analyzed_once(self, github, config):
        result = run(base_input(), config)
        trees = [name for kind, name in github.calls if kind == "tree"]
        assert trees.count("acme/limiter") == 1
        assert set(result["repositories"]) == {"acme/limiter", "big/framework"}

    def test_facts_and_caps(self, github, config):
        repos = run(base_input(), config)["repositories"]
        good = repos["acme/limiter"]
        assert good["cap"] == "adopt_as_dependency"
        assert good["scores"]["code_quality"] >= 75
        assert good["dependencies"]["status"] == "parsed"
        assert "Sliding window" in good["evidence"]["readme_excerpt"]
        assert repos["big/framework"]["cap"] == "reference_architecture_only"

    def test_component_relevance_is_per_component(self, github, config):
        result = run(base_input(), config)
        store = result["components"][1]["candidates"][0]
        assert store["repository"] == "acme/limiter"
        assert store["relevance"]["missing_terms"] == ["distributed"]

    def test_completed_status(self, github, config):
        result = run(base_input(), config)
        assert result["status"] == "completed"
        assert result["phase"] == "search"

    def test_no_candidates_component(self, github, config):
        data = base_input()
        data["components"].append(component("ui", queries=("nothing here",)))
        ui = run(data, config)["components"][2]
        assert ui["status"] == "no_candidates"
        assert ui["candidates"] == []

    def test_candidates_per_component_limit(self, github, config):
        core = run(base_input(candidates_per_component=1), config)["components"][0]
        assert [c["repository"] for c in core["candidates"]] == ["acme/limiter"]


class TestPartialFailures:
    def test_search_error_marks_partial(self, github, config):
        github.search_errors["rate limit go"] = {"kind": "http", "detail": "HTTP 422"}
        result = run(base_input(), config)
        assert result["status"] == "partial"
        assert result["warnings"][0]["type"] == "search_failed"

    def test_rate_limit_skips_remaining_queries(self, github, config):
        github.search_errors["sliding window go"] = {"kind": "rate_limit", "detail": "x"}
        result = run(base_input(), config)
        types = [w["type"] for w in result["warnings"]]
        assert types == ["rate_limit", "search_skipped", "search_skipped"]
        assert result["status"] == "partial"

    def test_tree_failure_is_a_data_gap_and_caps(self, github, config):
        github.trees["acme/limiter"] = None
        result = run(base_input(), config)
        facts = result["repositories"]["acme/limiter"]
        assert "file_tree" in facts["data_gaps"]
        assert facts["dependencies"]["status"] == "unavailable"
        assert facts["cap"] == "fork_and_modify"
        assert result["status"] == "partial"


class TestRerunOnly:
    def test_rerun_replaces_only_named_component(self, github, config):
        first = run(base_input(), config)
        data = base_input()
        data["components"][1]["search_queries"] = ["redis limiter"]
        github.add_repo(repo("new/redis-limiter", description="redis limiter"),
                        ["redis limiter"], tree=["go.mod"], readme="redis",
                        files={"go.mod": "module y\n"})
        second = run(data, config, previous=first, only=["store"])

        assert second["components"][0] == first["components"][0]
        store = second["components"][1]
        assert store["round"] == 2
        assert store["query_history"] == [["redis rate limit"], ["redis limiter"]]
        assert [c["repository"] for c in store["candidates"]] == ["new/redis-limiter"]
        assert set(second["repositories"]) == {
            "acme/limiter", "big/framework", "new/redis-limiter"}

    def test_round_limit_enforced(self, github, config):
        result = run(base_input(), config)
        for _ in range(config["search"]["max_rounds"] - 1):
            result = run(base_input(), config, previous=result, only=["store"])
        with pytest.raises(ScriptFailure) as exc:
            run(base_input(), config, previous=result, only=["store"])
        assert exc.value.reason_code == "max_rounds_exceeded"

    def test_changed_requirement_rejected(self, github, config):
        first = run(base_input(), config)
        with pytest.raises(ScriptFailure):
            run(base_input(requirement="別的需求"), config, previous=first, only=["store"])

    def test_unknown_component_rejected(self, github, config):
        first = run(base_input(), config)
        with pytest.raises(ScriptFailure):
            run(base_input(), config, previous=first, only=["nope"])
