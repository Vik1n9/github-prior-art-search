from typing import Any, Dict, List, Optional

from .common import load_config
from .score_candidates import RISK_RANK, overall_dependency_risk

ADOPTABLE_DECISIONS = ("adopt_as_dependency", "fork_and_modify", "use_as_template",
                       "reference_architecture_only")
LICENSE_GATED_DECISIONS = ("adopt_as_dependency", "fork_and_modify", "use_as_template")

NEXT_STEPS = {
    "adopt_as_dependency": [
        "以套件管理器加入依賴並鎖定版本。",
        "閱讀上游 API 文件與變更日誌。",
        "建立升級與相容性檢查流程。",
    ],
    "fork_and_modify": [
        "Fork 倉庫並以分支管理修改差異。",
        "評估長期維護責任與上游同步策略。",
        "保留原始授權聲明與版權標頭。",
    ],
    "use_as_template": [
        "複製骨架後移除不需要的模組。",
        "重寫業務邏輯層與領域模型。",
        "保留授權與版權標頭，補上自有文件。",
    ],
    "reference_architecture_only": [
        "僅參考其架構、分層與資料流設計。",
        "不直接複製程式碼，自行實作並撰寫測試。",
    ],
    "avoid_due_to_risk": [
        "風險過高，不建議採用其程式碼。",
        "如仍需借鏡，僅限架構概念層次。",
    ],
    "build_in_house": [
        "無合適候選，依核心功能自行開發。",
        "優先實作差異化功能，先建立骨架與測試。",
    ],
}


def _meets(value: float, threshold: Any) -> bool:
    return value >= float(threshold)


def _dependency_risk_acceptable(dependency_risk: str, max_level: str) -> bool:
    return RISK_RANK.get(dependency_risk, 0) <= RISK_RANK.get(max_level, 1)


def _should_avoid(risks: List[Dict[str, str]], metadata: Dict[str, Any]) -> bool:
    if metadata.get("archived") is True:
        return True
    return any(r.get("type") == "license_risk" and r.get("level") == "high"
               for r in risks)


def _satisfies(rule_name: str, condition: Dict[str, Any], scores: Dict[str, Any],
               dependency_risk: str) -> bool:
    if not (_meets(scores["total"], condition["total_score"])
            and _meets(scores["relevance"], condition["relevance"])):
        return False
    if rule_name in LICENSE_GATED_DECISIONS and \
            not _meets(scores["license_fit"], condition["license_fit"]):
        return False
    if "maintenance_activity" in condition and \
            not _meets(scores["maintenance_activity"], condition["maintenance_activity"]):
        return False
    if "dependency_risk_max" in condition and \
            not _dependency_risk_acceptable(dependency_risk,
                                            condition["dependency_risk_max"]):
        return False
    return True


def decide_reuse(scores: Dict[str, Any], risks: List[Dict[str, str]],
                 metadata: Dict[str, Any],
                 config: Optional[Dict[str, Any]] = None) -> str:
    rules = (config or load_config())["decision_rules"]
    dependency_risk = overall_dependency_risk(risks)

    for rule_name in rules["evaluation_order"]:
        if rule_name == "avoid_due_to_risk":
            if _should_avoid(risks, metadata):
                return rule_name
            continue
        if _satisfies(rule_name, rules[rule_name], scores, dependency_risk):
            return rule_name

    return "insufficient_fit"


def build_recommendation(analyzed: List[Dict[str, Any]],
                         config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ranked = sorted(analyzed, key=lambda c: c["scores"]["total"], reverse=True)
    best = next((c for c in ranked
                 if c["reuse_decision"] in ADOPTABLE_DECISIONS), None)

    if best is None:
        reason = "所有候選均未達採用門檻" if analyzed else "搜尋未找到符合條件的候選專案"
        return {
            "primary_action": "build_in_house",
            "primary_repository": None,
            "reason": f"{reason}，建議自行開發。",
            "build_in_house_parts": [],
            "next_steps": NEXT_STEPS["build_in_house"],
        }

    decision = best["reuse_decision"]
    scores = best["scores"]
    return {
        "primary_action": decision,
        "primary_repository": best["repository"],
        "reason": f"{best['repository']} 總分 {scores['total']}"
                  f"（相關度 {scores['relevance']}、"
                  f"維護活躍度 {scores['maintenance_activity']}、"
                  f"授權契合 {scores['license_fit']}），符合 {decision} 規則門檻。",
        "build_in_house_parts": [],
        "next_steps": NEXT_STEPS[decision],
    }


def candidate_summary(candidate: Dict[str, Any]) -> str:
    scores = candidate["scores"]
    dependencies = candidate.get("dependencies") or {}
    spdx = (candidate.get("license") or {}).get("spdx_id") or "unknown"
    return (
        f"{candidate.get('stars', 0)} 星 {candidate.get('language') or '未知語言'}；"
        f"授權 {spdx}（fit={scores.get('license_fit', 0)}）；"
        f"依賴 {dependencies.get('total_count', 0)} 筆"
        f"（未固定 {dependencies.get('unpinned_count', 0)}）；"
        f"總分 {scores.get('total', 0)}；決策 {candidate.get('reuse_decision')}。"
    )
