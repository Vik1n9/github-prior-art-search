import copy
import sys
import time
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

NOW_TS = 1790000000.0


def iso_days_ago(days, now_ts=NOW_TS):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts - days * 86400))


@pytest.fixture(scope="session")
def config():
    from scripts.common import load_config
    return load_config()


def repo(full_name="owner/repo", stars=500, archived=False, disabled=False,
         pushed_days_ago=10, spdx="MIT", **extra):
    return {
        "full_name": full_name,
        "name": full_name.split("/")[-1],
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "forks_count": 10,
        "archived": archived,
        "disabled": disabled,
        "pushed_at": iso_days_ago(pushed_days_ago),
        "default_branch": "main",
        "description": "",
        "topics": [],
        "language": "Go",
        "license": {"spdx_id": spdx} if spdx else None,
        **extra,
    }


def component(cid="core", queries=("q1",), must_have=("feature a", "feature b"),
              match_terms=("rate limit", "sliding window"), **extra):
    return {
        "id": cid,
        "name": f"組件 {cid}",
        "must_have": list(must_have),
        "match_terms": list(match_terms),
        "search_queries": list(queries),
        **extra,
    }


class FakeGitHub:
    """Stands in for scripts.search_github network calls."""

    def __init__(self):
        self.search_results = {}
        self.search_errors = {}
        self.trees = {}
        self.readmes = {}
        self.files = {}
        self.releases = {}
        self.calls = []

    def add_repo(self, meta, queries, tree=(), readme=None, files=None, release=True):
        for query in queries:
            self.search_results.setdefault(query, []).append(copy.deepcopy(meta))
        self.trees[meta["full_name"]] = list(tree)
        self.readmes[meta["full_name"]] = readme
        self.files[meta["full_name"]] = files or {}
        self.releases[meta["full_name"]] = release

    def search_repositories(self, query, token, min_stars):
        self.calls.append(("search", query))
        if query in self.search_errors:
            return [], self.search_errors[query]
        return copy.deepcopy(self.search_results.get(query, [])), None

    def fetch_file_tree(self, full_name, branch, token):
        self.calls.append(("tree", full_name))
        tree = self.trees.get(full_name)
        if tree is None:
            return [], False, {"kind": "http", "detail": "HTTP 500"}
        return list(tree), False, None

    def fetch_readme(self, full_name, token):
        return self.readmes.get(full_name), None

    def fetch_raw_file(self, full_name, branch, path, token):
        return self.files.get(full_name, {}).get(path), None

    def fetch_has_release_or_tag(self, full_name, token):
        return self.releases.get(full_name, False), None


@pytest.fixture
def fake_github(monkeypatch):
    from scripts import search_github
    fake = FakeGitHub()
    for name in ("search_repositories", "fetch_file_tree", "fetch_readme",
                 "fetch_raw_file", "fetch_has_release_or_tag"):
        monkeypatch.setattr(search_github, name, getattr(fake, name))
    return fake
