# -*- coding: utf-8 -*-
"""腳本決策（§14）：最終採用建議由規則產生，模型不得推翻。

評估優先序（config.decision_rules.evaluation_order）：
  avoid_due_to_risk > adopt_as_dependency > fork_and_modify
  > use_as_template > reference_architecture_only
全數不符 → insufficient_fit；若所有候選皆不符門檻，整體建議 build_in_house。
"""
from typing import Any, Dict, List, Optional

from common import load_config
from score_candidates import overall_dependency_risk

RISK_RANK = {"low": 0, "medium": 1, "high": 2}

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


def _risk_ok(dep_risk: str, max_level: str) -> bool:
    return RISK_RANK.get(dep_risk, 0) <= RISK_RANK.get(max_level, 1)


def decide_reuse(scores: Dict[str, Any], risks: List[Dict[str, str]],
                 metadata: Dict[str, Any],
                 config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config or load_config()
    rules = cfg["decision_rules"]
    order = rules["evaluation_order"]
    dep_risk = overall_dependency_risk(risks)
    license_risk_high = any(r.get("type") == "license_risk" and r.get("level") == "high"
                            for r in risks)

    for rule_name in order:
        if rule_name == "avoid_due_to_risk":
            if license_risk_high or metadata.get("archived") is True:
                return rule_name
            continue

        cond = rules[rule_name]
        if not (_meets(scores["total"], cond["total_score"])
                and _meets(scores["relevance"], cond["relevance"])):
            continue
        if rule_name in ("adopt_as_dependency", "fork_and_modify", "use_as_template"):
            if not _meets(scores["license_fit"], cond["license_fit"]):
                continue
        if rule_name == "adopt_as_dependency":
            if (not _meets(scores["maintenance_activity"], cond["maintenance_activity"])
                    or not _risk_ok(dep_risk, cond["dependency_risk_max"])):
                continue
        elif rule_name == "fork_and_modify":
            if not _meets(scores["maintenance_activity"], cond["maintenance_activity"]):
                continue
        return rule_name

    return "insufficient_fit"


def build_recommendation(analyzed: List[Dict[str, Any]], config: Optional[Dict[str, Any]] = None
                         ) -> Dict[str, Any]:
    cfg = config or load_config()
    adoptable = ("adopt_as_dependency", "fork_and_modify", "use_as_template",
                 "reference_architecture_only")

    ranked = sorted(analyzed, key=lambda c: c["scores"]["total"], reverse=True)
    best = None
    for candidate in ranked:
        if candidate["reuse_decision"] in adoptable:
            best = candidate
            break

    if best is None:
        reason = "所有候選均未達採用門檻" if analyzed else "搜尋未找到符合條件的候選專案"
        primary_action = "build_in_house"
        parts_source: List[str] = []
        return {
            "primary_action": primary_action,
            "primary_repository": None,
            "reason": f"{reason}，建議自行開發。",
            "build_in_house_parts": parts_source,
            "next_steps": NEXT_STEPS["build_in_house"],
        }

    decision = best["reuse_decision"]
    scores = best["scores"]
    reason = (
        f"{best['repository']} 總分 {scores['total']}（相關度 {scores['relevance']}、"
        f"維護活躍度 {scores['maintenance_activity']}、授權契合 {scores['license_fit']}），"
        f"符合 {decision} 規則門檻。"
    )
    return {
        "primary_action": decision,
        "primary_repository": best["repository"],
        "reason": reason,
        "build_in_house_parts": [],
        "next_steps": NEXT_STEPS[decision],
    }


def candidate_summary(candidate: Dict[str, Any]) -> str:
    """腳本產生的結構化摘要（非模型生成）。"""
    scores = candidate["scores"]
    deps = candidate.get("dependencies") or {}
    license_info = candidate.get("license") or {}
    spdx = license_info.get("spdx_id") or "unknown"
    return (
        f"{candidate.get('stars', 0)} 星 {candidate.get('language') or '未知語言'}；"
        f"授權 {spdx}（fit={scores.get('license_fit', 0)}）；"
        f"依賴 {deps.get('total_count', 0)} 筆（未固定 {deps.get('unpinned_count', 0)}）；"
        f"總分 {scores.get('total', 0)}；決策 {candidate.get('reuse_decision')}。"
    )
