import pytest

from scripts.parse_dependencies import (analyze_dependencies, build_dependency_list,
                                        dependency_risks, find_lockfiles,
                                        find_manifests, is_pinned_version,
                                        parse_cargo_toml, parse_gradle,
                                        summarize_dependencies)


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
    def _summary(self, total, unpinned, lockfile=True, status="parsed"):
        return {
            "status": status,
            "manifests_found": ["npm"],
            "lockfiles_found": ["package-lock.json"] if lockfile else [],
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

    def test_threshold_500_total_is_high_and_not_double_counted(self, config):
        rules = dependency_risks(self._summary(501, 0), config)
        assert [r["level"] for r in rules] == ["high"]

    def test_unparsed_summary_carries_no_computed_risk(self, config):
        assert dependency_risks(self._summary(0, 0, lockfile=False,
                                              status="failed"), config) == []

    def test_threshold_20_unpinned(self, config):
        rules = dependency_risks(self._summary(50, 21), config)
        assert any("未固定" in r["detail"] for r in rules)
        assert dependency_risks(self._summary(50, 20), config) == []

    def test_no_lockfile_medium_risk(self, config):
        rules = dependency_risks(self._summary(5, 0, lockfile=False), config)
        assert {"type": "dependency_risk", "level": "medium"} in \
            [{k: v for k, v in r.items() if k != "detail"} for r in rules]

    def test_no_manifest_is_reported_as_such(self, config):
        summary, warnings = analyze_dependencies([], lambda p: (None, None))
        assert summary["status"] == "no_manifest"
        assert warnings == []

    def test_unfetchable_manifest_is_failed_not_zero(self, config):
        summary, warnings = analyze_dependencies(["go.mod"], lambda p: (None, None))
        assert summary["status"] == "failed"
        assert warnings[0]["type"] == "dependency_parsing_failed"

    def test_unparsable_manifest_is_failed(self, config):
        summary, _ = analyze_dependencies(["package.json"], lambda p: ("{oops", None))
        assert summary["status"] == "failed"

    def test_details_are_truncated(self, config):
        deps = [{"type": "runtime", "pinned": True, "name": str(i)} for i in range(80)]
        summary = summarize_dependencies(deps, [], {"npm": ["package.json"]},
                                         detail_limit=50)
        assert len(summary["details"]) == 50
        assert summary["details_truncated"] is True
        assert summary["total_count"] == 80

    def test_every_configured_manifest_has_a_parser(self, config):
        from scripts.parse_dependencies import PARSERS
        for ecosystem, spec in config["dependency_manifests"].items():
            for file_name in spec["files"]:
                assert (ecosystem, file_name) in PARSERS


class TestDevDependenciesAreKept:
    def test_cargo_dev_and_build_dependencies(self):
        parsed = parse_cargo_toml(
            '[dependencies]\nserde = "1.0.100"\n'
            '[dev-dependencies]\ncriterion = "0.5"\n'
            '[build-dependencies]\ncc = "1.0"\n')
        assert [d["name"] for d in parsed["runtime"]] == ["serde"]
        assert sorted(d["name"] for d in parsed["dev"]) == ["cc", "criterion"]

    def test_gradle_test_scope_is_dev(self):
        parsed = parse_gradle(
            "dependencies {\n"
            "  implementation 'org.springframework:spring-core:5.3.0'\n"
            "  testImplementation 'junit:junit:4.13'\n"
            "}")
        assert [d["name"] for d in parsed["runtime"]] == ["org.springframework:spring-core"]
        assert [d["name"] for d in parsed["dev"]] == ["junit:junit"]

    def test_dev_dependencies_reach_the_summary(self):
        manifests = {"rust": ["Cargo.toml"]}
        contents = {"Cargo.toml": '[dependencies]\nserde = "1.0.100"\n'
                                  '[dev-dependencies]\ncriterion = "0.5"\n'}
        summary = summarize_dependencies(
            build_dependency_list(manifests, contents), [], manifests)
        assert summary["runtime_count"] == 1
        assert summary["dev_count"] == 1
        assert summary["total_count"] == 2
