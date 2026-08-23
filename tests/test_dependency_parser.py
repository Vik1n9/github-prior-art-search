# -*- coding: utf-8 -*-
"""§12 依賴解析驗收：清單偵測、pinned 判定、統計與風險門檻。"""
import pytest

from parse_dependencies import (analyze_dependencies, build_dependency_list,
                               dependency_risks, find_lockfiles, find_manifests,
                               is_pinned_version, summarize_dependencies)


class TestPinnedDetection:
    @pytest.mark.parametrize("version,expected", [
        ("1.2.3", True),
        ("v1.9.1", True),
        ("^18.2.0", False),
        ("~1.2", False),
        ("latest", False),
        ("next", False),
        ("*", False),
        ("", False),
        ("1.x", False),
        (">=2.0", False),
        ("29.0.0", True),
    ])
    def test_is_pinned(self, version, expected):
        assert is_pinned_version(version) is expected


class TestManifestDetection:
    def test_find_manifests_top_level_only(self, config):
        paths = ["package.json", "src/index.ts", "docs/guide.md",
                 "sub/package.json"]
        manifests = find_manifests(paths)
        assert manifests == {"npm": ["package.json"]}

    def test_find_lockfiles(self, config):
        assert find_lockfiles(["package-lock.json", "go.sum"]) == ["go.sum", "package-lock.json"]


class TestParsers:
    def test_package_json(self):
        deps = build_dependency_list(
            {"npm": ["package.json"]},
            {"package.json": '{"dependencies": {"react": "^18.2.0"},'
                             ' "devDependencies": {"jest": "29.0.0"}}'})
        by_name = {d["name"]: d for d in deps}
        assert by_name["react"]["type"] == "runtime"
        assert by_name["react"]["pinned"] is False
        assert by_name["jest"]["type"] == "dev"
        assert by_name["jest"]["pinned"] is True

    def test_requirements_txt(self):
        deps = build_dependency_list(
            {"python": ["requirements.txt"]},
            {"requirements.txt": "requests==2.31.0\nflask>=2.0\n# c\nnumpy"})
        by_name = {d["name"]: d for d in deps}
        assert by_name["requests"]["pinned"] is True
        assert by_name["flask"]["pinned"] is False
        assert by_name["numpy"]["pinned"] is False  # 無版本 → 未固定

    def test_go_mod(self):
        deps = build_dependency_list(
            {"go": ["go.mod"]},
            {"go.mod": "module x\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n"})
        assert deps[0]["ecosystem"] == "go"
        assert deps[0]["pinned"] is True

    def test_invalid_json_marks_failure(self):
        with pytest.raises(ValueError):
            build_dependency_list({"npm": ["package.json"]}, {"package.json": "{oops"})


class TestSummaryAndRisks:
    def _summary(self, total, unpinned, lockfile=True):
        return {
            "manifests_found": ["npm"], "lockfiles_found": ["package-lock.json"] if lockfile else [],
            "lockfile_present": lockfile, "runtime_count": total, "dev_count": 0,
            "total_count": total, "unpinned_count": unpinned, "details": [],
        }

    def test_counts(self, config):
        deps = [{"type": "runtime", "pinned": True}] * 30 + \
               [{"type": "dev", "pinned": False}] * 10
        summary = summarize_dependencies(deps, ["yarn.lock"], {"npm": ["package.json"]})
        assert summary["runtime_count"] == 30
        assert summary["dev_count"] == 10
        assert summary["unpinned_count"] == 10
        assert summary["lockfile_present"] is True

    def test_threshold_200_total(self, config):
        rules = dependency_risks(self._summary(201, 0), config)
        assert any("超過門檻 200" in r["detail"] for r in rules)
        assert dependency_risks(self._summary(200, 0), config) == []

    def test_threshold_20_unpinned(self, config):
        rules = dependency_risks(self._summary(50, 21), config)
        assert any("未固定" in r["detail"] for r in rules)
        assert dependency_risks(self._summary(50, 20), config) == []

    def test_no_lockfile_medium_risk(self, config):
        rules = dependency_risks(self._summary(5, 0, lockfile=False), config)
        assert {"type": "dependency_risk", "level": "medium"} in \
            [{k: v for k, v in r.items() if k != "detail"} for r in rules]

    def test_no_manifests_returns_empty_summary_with_warning_free(self, config):
        summary, warnings = analyze_dependencies([], lambda p: None)
        assert summary["total_count"] == 0
        assert warnings == []
