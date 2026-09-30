import copy
import json

import pytest

from conftest import NOW_TS, component, repo
from scripts.common import ScriptFailure
from scripts.finalize import build_final
from scripts.pipeline import run_search
from test_pipeline import GOOD_FILES, GOOD_TREE, README, base_input


@pytest.fixture
def result(fake_github, config):
    fake_github.add_repo(
        repo("acme/limiter", stars=2000, description="Sliding window rate limiter",
             topics=["redis"]),
        ["sliding window go", "rate limit go", "redis rate limit"],
        tree=GOOD_TREE, readme=README, files=GOOD_FILES)
    fake_github.add_repo(
        repo("gpl/limiter", description="rate limit", spdx="GPL-3.0"),
        ["rate limit go"], tree=["go.mod"], files={"go.mod": "module g\n"})
    return run_search(base_input(), "token", config, now_ts=NOW_TS)


def assessment(**overrides):
    data = {
        "components": [
            {
                "id": "core",
                "verdict": "reuse",
                "selected": {
                    "repository": "acme/limiter",
                    "decision": "adopt_as_dependency",
                    "fit": "partial",
                    "covered": ["feature a"],
                    "gaps": ["feature b"],
                    "evidence": ["README: Sliding window rate limit for Go."],
                    "rationale": "涵蓋滑動視窗，缺 feature b。",
                },
                "alternatives": [{"repository": "gpl/limiter",
                                  "decision": "reference_architecture_only",
                                  "note": "GPL，僅參考。"}],
            },
            {"id": "store", "verdict": "build_in_house", "rationale": "無合適 Redis 實作。"},
        ],
        "executive_summary": "核心可重用，儲存自行開發。",
        "notable_observations": ["觀察一"],
    }
    data.update(overrides)
    return data


def rejected(data, result):
    with pytest.raises(ScriptFailure) as exc:
        build_final(result, data, "0" * 64)
    assert exc.value.reason_code == "invalid_assessment"
    return str(exc.value)


def core_selected(data):
    return data["components"][0]["selected"]


class TestValidAssessment:
    def test_plan_and_build_in_house_parts(self, result):
        final = build_final(result, assessment(), "a" * 64)
        core, store = final["plan"]
        assert core["decision"] == "adopt_as_dependency"
        assert core["cap"] == "adopt_as_dependency"
        assert core["alternatives"][0]["cap"] == "reference_architecture_only"
        assert store["verdict"] == "build_in_house"
        assert final["build_in_house_parts"] == [
            {"component": "core", "name": "組件 core", "items": ["feature b"],
             "reason": "partial_fit:acme/limiter"},
            {"component": "store", "name": "組件 store",
             "items": ["feature a", "feature b"], "reason": "no_suitable_candidate"},
        ]
        assert final["result_sha256"] == "a" * 64


class TestGuardrails:
    def test_decision_above_cap_rejected(self, result):
        data = assessment()
        data["components"][0]["alternatives"][0]["decision"] = "fork_and_modify"
        assert "高於腳本上限" in rejected(data, result)

    def test_repository_outside_candidates_rejected(self, result):
        data = assessment()
        core_selected(data)["repository"] = "made/up"
        assert "不在此組件的候選清單中" in rejected(data, result)

    def test_candidate_of_other_component_rejected(self, result):
        data = assessment()
        data["components"][1] = {
            "id": "store", "verdict": "reuse",
            "selected": {**core_selected(assessment()), "repository": "gpl/limiter",
                         "decision": "reference_architecture_only"}}
        assert "不在此組件的候選清單中" in rejected(data, result)

    def test_covered_and_gaps_must_partition_must_have(self, result):
        data = assessment()
        core_selected(data)["gaps"] = []
        message = rejected(data, result)
        assert "正好等於 must_have" in message
        assert "fit=partial 時 gaps 不得為空" in message

    def test_full_fit_with_gaps_rejected(self, result):
        data = assessment()
        core_selected(data)["fit"] = "full"
        assert "fit=full" in rejected(data, result)

    def test_nothing_covered_must_be_build_in_house(self, result):
        data = assessment()
        core_selected(data).update(covered=[], gaps=["feature a", "feature b"])
        assert "改判 build_in_house" in rejected(data, result)

    def test_evidence_required(self, result):
        data = assessment()
        core_selected(data)["evidence"] = []
        assert "evidence" in rejected(data, result)

    def test_missing_component_rejected(self, result):
        data = assessment()
        data["components"].pop()
        assert "缺少組件評估：store" in rejected(data, result)

    def test_duplicate_component_rejected(self, result):
        data = assessment()
        data["components"].append(copy.deepcopy(data["components"][1]))
        assert "重複" in rejected(data, result)

    def test_build_in_house_with_selected_rejected(self, result):
        data = assessment()
        data["components"][1]["selected"] = core_selected(data)
        assert "不得有 selected" in rejected(data, result)

    def test_summary_length_limited(self, result, config):
        limit = config["assessment"]["max_summary_chars"]
        assert "executive_summary" in rejected(
            assessment(executive_summary="字" * (limit + 1)), result)

    def test_observation_count_limited(self, result, config):
        count = config["assessment"]["max_observations"] + 1
        assert "notable_observations" in rejected(
            assessment(notable_observations=["x"] * count), result)

    def test_old_result_format_rejected(self, result):
        with pytest.raises(ScriptFailure) as exc:
            build_final({**result, "schema_version": 2}, assessment(), "0" * 64)
        assert exc.value.reason_code == "invalid_result"

    def test_reuse_without_candidates_rejected(self, fake_github, config):
        data = base_input(components=[component("core", queries=("none",))])
        empty = run_search(data, "token", config, now_ts=NOW_TS)
        verdict = {"components": [{"id": "core", "verdict": "reuse",
                                   "selected": core_selected(assessment())}],
                   "executive_summary": "x"}
        assert "只能是 build_in_house" in rejected(verdict, empty)


class TestCli:
    def test_search_then_finalize(self, fake_github, tmp_path, monkeypatch, capsys):
        import main
        fake_github.add_repo(
            repo("acme/limiter", stars=2000, description="Sliding window rate limiter",
                 topics=["redis"]),
            ["sliding window go", "rate limit go", "redis rate limit"],
            tree=GOOD_TREE, readme=README, files=GOOD_FILES)
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        input_path = tmp_path / "input.json"
        input_path.write_text(json.dumps(base_input()), encoding="utf-8")
        out = tmp_path / "out"

        assert main.main(["search", "--input", str(input_path),
                          "--output-dir", str(out)]) == 0
        assert (out / "result.md").read_text(encoding="utf-8").startswith("# GitHub")

        data = assessment()
        data["components"][0].pop("alternatives")
        assessment_path = tmp_path / "assessment.json"
        assessment_path.write_text(json.dumps(data), encoding="utf-8")
        assert main.main(["finalize", "--assessment", str(assessment_path),
                          "--output-dir", str(out)]) == 0

        final = json.loads((out / "final.json").read_text(encoding="utf-8"))
        assert final["phase"] == "final"
        report = (out / "final.md").read_text(encoding="utf-8")
        assert "acme/limiter" in report and "需自行開發部分" in report

        assert main.main(["search", "--input", str(input_path),
                          "--output-dir", str(out)]) == 0
        assert not (out / "final.json").exists()

    def test_search_without_token_fails(self, tmp_path, monkeypatch):
        import main
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        input_path = tmp_path / "input.json"
        input_path.write_text(json.dumps(base_input()), encoding="utf-8")
        with pytest.raises(ScriptFailure) as exc:
            main.main(["search", "--input", str(input_path),
                       "--output-dir", str(tmp_path)])
        assert exc.value.reason_code == "missing_github_token"
