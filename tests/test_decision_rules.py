from scripts.build_recommendation import build_recommendation, decide_reuse
from scripts.score_candidates import calculate_scores, compute_risks


def scores(total=90, relevance=90, license_fit=100, maintenance=90):
    return {
        "relevance": relevance, "reusability": 80,
        "maintenance_activity": maintenance, "code_quality": 70,
        "documentation": 70, "license_fit": license_fit, "total": total,
    }


NO_RISKS = []


class TestDecideReuse:
    def test_adopt_as_dependency_all_thresholds_met(self, config):
        assert decide_reuse(scores(), NO_RISKS, {}, config) == "adopt_as_dependency"

    def test_adopt_blocked_by_high_dep_risk(self, config):
        risks = [{"type": "dependency_risk", "level": "high", "detail": ""}]
        result = decide_reuse(scores(), risks, {}, config)
        assert result == "fork_and_modify"

    def test_fork_when_below_adopt_relevance(self, config):
        s = scores(relevance=76)
        assert decide_reuse(s, NO_RISKS, {}, config) == "fork_and_modify"

    def test_template_when_maintenance_low(self, config):
        s = scores(total=76, relevance=76, maintenance=40)
        assert decide_reuse(s, NO_RISKS, {}, config) == "use_as_template"

    def test_reference_only(self, config):
        s = scores(total=60, relevance=65, license_fit=100, maintenance=10)
        assert decide_reuse(s, NO_RISKS, {}, config) == "reference_architecture_only"

    def test_insufficient_fit(self, config):
        s = scores(total=50, relevance=50)
        assert decide_reuse(s, NO_RISKS, {}, config) == "insufficient_fit"

    def test_avoid_due_to_license_risk_overrides_everything(self, config):
        risks = [{"type": "license_risk", "level": "high", "detail": "AGPL"}]
        assert decide_reuse(scores(), risks, {}, config) == "avoid_due_to_risk"

    def test_avoid_when_archived_even_with_perfect_scores(self, config):
        assert decide_reuse(scores(), NO_RISKS, {"archived": True}, config) == \
            "avoid_due_to_risk"


class TestBoundaries:
    def test_exact_thresholds_pass(self, config):
        s = scores(total=80, relevance=80, license_fit=90, maintenance=70)
        assert decide_reuse(s, [], {}, config) == "adopt_as_dependency"

    def test_one_point_below_fails(self, config):
        s = scores(total=79.9, relevance=80, license_fit=90, maintenance=70)
        assert decide_reuse(s, [], {}, config) != "adopt_as_dependency"

    def test_medium_dep_risk_allows_adopt(self, config):
        risks = [{"type": "dependency_risk", "level": "medium", "detail": ""}]
        assert decide_reuse(scores(), risks, {}, config) == "adopt_as_dependency"


class TestBuildRecommendation:
    def _candidate(self, name, total, decision):
        return {"repository": name, "scores": scores(total=total),
                "reuse_decision": decision}

    def test_best_adoptable_wins(self, config):
        candidates = [
            self._candidate("a/high-risk", 95, "avoid_due_to_risk"),
            self._candidate("b/template", 72, "use_as_template"),
            self._candidate("c/adopt", 85, "adopt_as_dependency"),
        ]
        rec = build_recommendation(candidates, config)
        assert rec["primary_action"] == "adopt_as_dependency"
        assert rec["primary_repository"] == "c/adopt"
        assert rec["build_in_house_parts"] == []

    def test_no_candidate_meets_threshold_builds_in_house(self, config):
        candidates = [self._candidate("a/low", 50, "insufficient_fit")]
        rec = build_recommendation(candidates, config)
        assert rec["primary_action"] == "build_in_house"
        assert rec["primary_repository"] is None

    def test_empty_candidates_builds_in_house(self, config):
        rec = build_recommendation([], config)
        assert rec["primary_action"] == "build_in_house"
        assert rec["next_steps"]


class TestFullScorePipeline:
    def test_calculate_and_risk_integration(self, config):
        repo_meta = {
            "full_name": "acme/task-admin-dashboard",
            "name": "task-admin-dashboard",
            "description": "Admin dashboard for game task ops: activity configuration, "
                           "reward engine and approval workflow.",
            "topics": ["admin-dashboard", "game-ops", "workflow"],
            "language": "TypeScript",
            "pushed_at": "2026-07-01T00:00:00Z",
            "archived": False,
        }
        input_data = {
            "project_goal": "admin dashboard for game task ops",
            "core_features": ["task configuration", "approval workflow"],
            "tech_stack": ["TypeScript"],
        }
        license_info = {"spdx_id": "MIT", "category": "preferred",
                        "license_fit_score": 100, "action": "allow_reuse",
                        "risk_level": "low", "source": "api_field"}
        deps = {"total_count": 30, "unpinned_count": 2, "lockfile_present": True}
        s = calculate_scores(input_data, repo_meta, license_info, deps,
                             "Task admin dashboard. Install with npm install. "
                             "Usage examples in docs/. Configure tasks and rewards.",
                             ["src/index.ts", ".github/workflows/ci.yml",
                              "package.json", "examples/demo.ts"],
                             has_release=True, now_ts=1787500000.0, config=config)
        assert 0 <= s["total"] <= 100
        assert s["relevance"] >= 70
        assert s["maintenance_activity"] == 100

        risks = compute_risks(license_info, [], repo_meta,
                              config["defaults"]["last_commit_within_days"])
        assert risks == []
        decision = decide_reuse(s, risks, repo_meta, config)
        assert decision in ("adopt_as_dependency", "fork_and_modify",
                            "use_as_template", "reference_architecture_only")
