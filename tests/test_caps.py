import pytest

from scripts.caps import compute_cap, compute_risks


def lic(category, spdx="X", source="api_field"):
    return {"category": category, "spdx_id": spdx, "source": source}


class TestCap:
    def test_clean_repo_allows_adoption(self, config):
        cap, reasons = compute_cap(lic("preferred", "MIT"), [], "parsed", 100, config)
        assert cap == "adopt_as_dependency"
        assert reasons == []

    @pytest.mark.parametrize("category", ["review_required", "high_risk", "unknown"])
    def test_non_permissive_license_caps_to_reference(self, config, category):
        cap, reasons = compute_cap(lic(category), [], "parsed", 100, config)
        assert cap == "reference_architecture_only"
        assert reasons

    def test_stale_repo_caps_to_fork(self, config):
        cap, _ = compute_cap(lic("preferred"), [], "parsed", 40, config)
        assert cap == "fork_and_modify"

    def test_high_dependency_risk_caps_to_fork(self, config):
        risks = [{"type": "dependency_risk", "level": "high", "detail": ""}]
        cap, _ = compute_cap(lic("preferred"), risks, "parsed", 100, config)
        assert cap == "fork_and_modify"

    def test_medium_dependency_risk_does_not_cap(self, config):
        risks = [{"type": "dependency_risk", "level": "medium", "detail": ""}]
        cap, _ = compute_cap(lic("preferred"), risks, "parsed", 100, config)
        assert cap == "adopt_as_dependency"

    @pytest.mark.parametrize("status", ["failed", "unavailable"])
    def test_unknown_dependencies_cap_to_fork(self, config, status):
        cap, _ = compute_cap(lic("preferred"), [], status, 100, config)
        assert cap == "fork_and_modify"

    def test_tightest_limit_wins(self, config):
        cap, reasons = compute_cap(lic("unknown"), [], "failed", 40, config)
        assert cap == "reference_architecture_only"
        assert len(reasons) == 3


class TestRisks:
    def test_sorted_high_first(self, config):
        risks = compute_risks(lic("review_required"),
                              [{"type": "dependency_risk", "level": "high", "detail": ""}],
                              "parsed", 100, 5, config)
        assert [r["level"] for r in risks] == ["high", "medium"]

    def test_stale_and_unknown_dependencies_flagged(self, config):
        risks = compute_risks(lic("preferred"), [], "failed", 40, 500, config)
        assert {r["type"] for r in risks} == {"dependency_risk", "maintenance_risk"}

    def test_unknown_push_time_described(self, config):
        risks = compute_risks(lic("preferred"), [], "parsed", 0, None, config)
        assert risks[0]["detail"].startswith("最後推送時間不明")

    def test_clean_repo_has_no_risk(self, config):
        assert compute_risks(lic("preferred"), [], "parsed", 100, 5, config) == []
