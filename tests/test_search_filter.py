from conftest import NOW_TS, repo
from scripts.search_github import (effective_max_age_days, effective_min_stars,
                                   ensure_star_filter, filter_repositories, merge_hits)


def _filter(items, exclude=(), min_stars=100, max_age=730):
    return filter_repositories(items, list(exclude), min_stars, max_age, NOW_TS)


class TestEffectiveFilters:
    def test_floor_enforced_below_100(self):
        assert effective_min_stars({"min_stars": 10}) == 100

    def test_input_above_floor_respected(self):
        assert effective_min_stars({"min_stars": 500}) == 500

    def test_max_age_from_input_or_config(self, config):
        assert effective_max_age_days({"last_commit_within_days": 365}) == 365
        assert effective_max_age_days({}) == config["defaults"]["last_commit_within_days"]


class TestFilter:
    def test_stars_below_floor_discarded(self):
        kept, discarded = _filter([repo("a/low", stars=99), repo("a/ok", stars=100)])
        assert [r["full_name"] for r in kept] == ["a/ok"]
        assert discarded == [{"repository": "a/low", "reason": "stars<100"}]

    def test_archived_and_disabled_discarded(self):
        kept, _ = _filter([repo("a/arch", archived=True), repo("a/dis", disabled=True),
                           repo("a/ok")])
        assert [r["full_name"] for r in kept] == ["a/ok"]

    def test_exclude_by_full_name_and_url(self):
        kept, _ = _filter([repo("Owner/Repo"), repo("x/y")],
                          exclude=["owner/repo", "https://github.com/x/y/"])
        assert kept == []

    def test_stale_push_discarded(self):
        kept, discarded = _filter([repo("old/repo", pushed_days_ago=800)])
        assert kept == []
        assert discarded[0]["reason"] == "last_push>730d"


class TestMergeHits:
    def test_same_repo_from_several_queries_is_merged(self):
        a, b = repo("a/a"), repo("b/b")
        merged = merge_hits([("q1", a), ("q2", a), ("q2", b), ("q2", a)])
        assert [(r["full_name"], qs) for r, qs in merged] == [
            ("a/a", ["q1", "q2"]), ("b/b", ["q2"])]


class TestStarFilterQuery:
    def test_appends_floor(self):
        assert ensure_star_filter("dashboard", 100) == "dashboard stars:>=100"

    def test_existing_star_qualifier_preserved(self):
        assert ensure_star_filter("dashboard stars:>=250", 100) == "dashboard stars:>=250"
