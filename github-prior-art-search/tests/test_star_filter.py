# -*- coding: utf-8 -*-
"""§22.1 驗收：星數 <100、archived、disabled 專案不得進入候選；黑名單與去重。"""
import time

import pytest
from conftest import repo

from search_github import (deduplicate, effective_min_stars, ensure_star_filter,
                           filter_repositories, sort_initial)


class TestEffectiveMinStars:
    def test_floor_enforced_below_100(self):
        assert effective_min_stars({"min_stars": 10}) == 100

    def test_input_above_floor_respected(self):
        assert effective_min_stars({"min_stars": 500}) == 500

    def test_default_is_100(self):
        assert effective_min_stars({}) == 100


class TestStarFilter:
    def test_stars_below_100_discarded(self):
        kept, discarded = filter_repositories([repo(stars=99), repo("a/b", stars=100)], [])
        assert [r["full_name"] for r in kept] == ["a/b"]
        assert discarded[0]["reason"].startswith("stars<")

    def test_archived_and_disabled_discarded(self):
        kept, _ = filter_repositories([
            repo("a/arch", archived=True, stars=1000),
            repo("a/dis", disabled=True, stars=1000),
            repo("a/ok", stars=1000),
        ], [])
        assert [r["full_name"] for r in kept] == ["a/ok"]

    def test_exclude_by_full_name_and_url(self):
        excluded = ["owner/repo", "https://github.com/x/y"]
        kept, _ = filter_repositories([repo(), repo("x/y", stars=300)], excluded)
        assert kept == []

    def test_last_commit_within_days(self, config):
        old = "2000-01-01T00:00:00Z"
        kept, discarded = filter_repositories([repo("old/repo", pushed_at=old)], [],
                                              now_ts=time.time())
        assert kept == []
        assert discarded[0]["reason"] == "last_commit>730d"


class TestDedupe:
    def test_duplicate_keeps_higher_stars(self):
        items = [repo("dup/repo", stars=120), repo("other", stars=50),
                 repo("dup/repo", stars=900)]
        result = deduplicate(items)
        names = [r["full_name"] for r in result]
        dup = next(r for r in result if r["full_name"] == "dup/repo")
        assert len(names) == len(set(names))
        assert dup["stargazers_count"] == 900

    def test_sort_initial_desc(self):
        result = sort_initial([repo("low", stars=101), repo("high", stars=9000),
                               repo("mid", stars=500)])
        assert [r["full_name"] for r in result] == ["high", "mid", "low"]


class TestStarFilterQuery:
    def test_ensure_star_filter_appends(self):
        assert ensure_star_filter("dashboard", 100) == "dashboard stars:>=100"

    def test_existing_star_filter_preserved(self):
        q = ensure_star_filter("dashboard stars:>=250", 100)
        assert q == "dashboard stars:>=250"
