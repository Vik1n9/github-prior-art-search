from typing import Any, Dict, List

from .common import ScriptFailure, load_skill_metadata, utc_now_iso
from .contract import validate_assessment
from .pipeline import SCHEMA_VERSION

NEXT_STEPS = {
    "adopt_as_dependency": [
        "以套件管理器加入依賴並鎖定版本。",
        "閱讀上游 API 文件與變更日誌，確認涵蓋的 must_have 行為。",
        "為缺口（gaps）撰寫轉接層或自行補齊。",
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
    "build_in_house": [
        "依 must_have 自行開發，先建立骨架與測試。",
    ],
}


def _plan_entry(entry: Dict[str, Any], component: Dict[str, Any],
                repositories: Dict[str, Any]) -> Dict[str, Any]:
    base = {
        "component": component["id"],
        "name": component["name"],
        "must_have": component["must_have"],
        "verdict": entry["verdict"],
        "search_rounds": component["round"],
        "alternatives": [
            {**alt, "cap": repositories[alt["repository"]]["cap"],
             "url": repositories[alt["repository"]]["url"]}
            for alt in entry.get("alternatives") or []],
    }
    if entry["verdict"] == "build_in_house":
        return {**base, "rationale": entry["rationale"],
                "next_steps": NEXT_STEPS["build_in_house"]}

    selected = entry["selected"]
    facts = repositories[selected["repository"]]
    return {
        **base,
        "repository": selected["repository"],
        "url": facts["url"],
        "decision": selected["decision"],
        "cap": facts["cap"],
        "cap_reasons": facts["cap_reasons"],
        "fit": selected["fit"],
        "covered": selected["covered"],
        "gaps": selected["gaps"],
        "evidence": selected["evidence"],
        "rationale": selected["rationale"],
        "license": facts["license"]["spdx_id"],
        "risks": facts["risks"],
        "next_steps": NEXT_STEPS[selected["decision"]],
    }


def _build_in_house_parts(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parts = []
    for item in plan:
        if item["verdict"] == "build_in_house":
            parts.append({"component": item["component"], "name": item["name"],
                          "items": item["must_have"], "reason": "no_suitable_candidate"})
        elif item["gaps"]:
            parts.append({"component": item["component"], "name": item["name"],
                          "items": item["gaps"],
                          "reason": f"partial_fit:{item['repository']}"})
    return parts


def build_final(result: Dict[str, Any], assessment: Dict[str, Any],
                result_sha256: str) -> Dict[str, Any]:
    if result.get("schema_version") != SCHEMA_VERSION or result.get("phase") != "search":
        raise ScriptFailure("result.json 不是本版 search 階段的輸出，請重新執行 search。",
                            "invalid_result")
    validate_assessment(assessment, result)
    by_id = {entry["id"]: entry for entry in assessment["components"]}
    plan = [_plan_entry(by_id[c["id"]], c, result["repositories"])
            for c in result["components"]]
    skill = load_skill_metadata()
    return {
        "skill": skill["name"],
        "schema_version": result["schema_version"],
        "phase": "final",
        "status": result["status"],
        "finalized_at": utc_now_iso(),
        "script_version": skill["version"],
        "result_sha256": result_sha256,
        "requirement": result["requirement"],
        "plan": plan,
        "build_in_house_parts": _build_in_house_parts(plan),
        "summary": {
            "executive_summary": assessment["executive_summary"],
            "notable_observations": assessment.get("notable_observations") or [],
        },
        "warnings": result["warnings"] + [
            w for name, facts in result["repositories"].items()
            for w in facts["warnings"]],
    }
