import pytest

from conftest import repo
from scripts.score_candidates import (code_quality_score, documentation_score,
                                      has_tests, health_score, maintenance_score,
                                      rank_score, relevance_score, reusability_score)

PARSED_DEPS = {"status": "parsed", "total_count": 10, "lockfile_present": True}


class TestWeightGroupsSumTo100:
    @pytest.mark.parametrize("group", [
        "relevance_weights", "health_weights", "rank_weights",
        "documentation_signals", "code_quality_signals", "reusability_signals"])
    def test_group_sums_to_100(self, config, group):
        assert sum(config[group].values()) == 100


class TestRelevance:
    TERMS = ["sliding window", "rate limit", "redis"]

    def _repo(self, **extra):
        return repo("acme/limiter", description="Sliding-window rate limiter",
                    topics=["redis"], **extra)

    def test_full_metadata_match_reaches_100(self, config):
        r = relevance_score(self.TERMS, ["Go"], self._repo(), None, 3, 3, config)
        assert r["score"] == 100.0
        assert r["missing_terms"] == []

    def test_readme_only_match_counts_less_than_metadata(self, config):
        bare = repo("acme/x", description="")
        in_readme = relevance_score(self.TERMS, [], bare,
                                    "sliding window rate limit on redis", 1, 3, config)
        in_meta = relevance_score(self.TERMS, [], self._repo(), None, 1, 3, config)
        assert in_readme["matched_in_readme"] == self.TERMS
        assert 0 < in_readme["score"] < in_meta["score"]

    def test_missing_terms_are_reported(self, config):
        r = relevance_score(self.TERMS, [], repo("a/b", description="redis client"),
                            None, 1, 3, config)
        assert r["missing_terms"] == ["sliding window", "rate limit"]

    def test_no_tech_stack_does_not_penalize(self, config):
        with_stack = relevance_score(self.TERMS, ["Go"], self._repo(), None, 3, 3, config)
        without = relevance_score(self.TERMS, [], self._repo(), None, 3, 3, config)
        assert with_stack["score"] == without["score"] == 100.0

    def test_unrelated_repo_scores_low(self, config):
        r = relevance_score(self.TERMS, ["Go"], repo("a/web", description="CSS framework",
                                                     language="CSS"), None, 1, 3, config)
        assert r["score"] < 10


class TestSignals:
    def test_go_tests_detected(self):
        assert has_tests(["limiter.go", "limiter_test.go"])

    def test_test_directory_detected(self):
        assert has_tests(["src/test/java/FooTest.java"])

    def test_no_tests(self):
        assert not has_tests(["main.go", "README.md", "latest.txt"])

    def test_code_quality_full_marks(self, config):
        paths = ["a_test.go", ".github/workflows/ci.yml", ".golangci.yml"]
        assert code_quality_score(paths, config)["score"] == 100

    def test_documentation_full_marks(self, config):
        readme = "## Install\ngo get x\n## Usage\n..."
        paths = ["docs/a.md", "examples/b.go"]
        assert documentation_score(readme, paths, config)["score"] == 100

    def test_reusability_uses_full_scale(self, config):
        paths = ["go.mod", "examples/a.go"]
        assert reusability_score(paths, PARSED_DEPS, True, config)["score"] == 100

    @pytest.mark.parametrize("status", ["no_manifest", "failed", "unavailable"])
    def test_unknown_dependencies_are_not_rewarded(self, config, status):
        deps = {"status": status, "total_count": 0, "lockfile_present": False}
        known = reusability_score([], PARSED_DEPS, False, config)["score"]
        unknown = reusability_score([], deps, False, config)["score"]
        assert unknown < known

    @pytest.mark.parametrize("days,expected", [
        (0, 100), (90, 100), (91, 85), (365, 70), (730, 40), (2000, 10), (None, 0)])
    def test_maintenance_buckets(self, config, days, expected):
        assert maintenance_score(days, config) == expected


class TestComposites:
    def test_perfect_health_is_100(self, config):
        parts = {"maintenance": 100, "code_quality": 100, "documentation": 100,
                 "reusability": 100}
        assert health_score(parts, config) == 100.0

    def test_rank_blends_relevance_and_health(self, config):
        assert rank_score(100, 100, config) == 100.0
        assert rank_score(100, 0, config) == 70.0
