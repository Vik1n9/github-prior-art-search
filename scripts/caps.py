from typing import Any, Dict, List, Optional, Tuple

from .common import load_config

RISK_RANK = {"low": 0, "medium": 1, "high": 2}
UNKNOWN_DEPENDENCY_STATUSES = ("failed", "unavailable")


def license_risk(license_info: Dict[str, Any]) -> Optional[Dict[str, str]]:
    category = license_info["category"]
    spdx = license_info.get("spdx_id")
    if category == "unknown":
        detail = ("存在授權檔但無法識別 SPDX" if license_info["source"] ==
                  "license_file_unparsed" else "未偵測到授權") + "，不得直接重用程式碼。"
        return {"type": "license_risk", "level": "high", "detail": detail}
    if category == "high_risk":
        return {"type": "license_risk", "level": "high",
                "detail": f"授權 {spdx} 屬高風險類別（網路 copyleft 或商用限制）。"}
    if category == "review_required":
        return {"type": "license_risk", "level": "medium",
                "detail": f"授權 {spdx} 需法務審查後才可重用程式碼。"}
    return None


def compute_risks(license_info: Dict[str, Any],
                  dependency_risk_list: List[Dict[str, str]],
                  dependency_status: str, maintenance: int,
                  days_since_push: Optional[int],
                  config: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    config = config or load_config()
    risks: List[Dict[str, str]] = []
    lic = license_risk(license_info)
    if lic:
        risks.append(lic)
    risks.extend(dependency_risk_list)
    if dependency_status in UNKNOWN_DEPENDENCY_STATUSES:
        risks.append({"type": "dependency_risk", "level": "medium",
                      "detail": "依賴清單無法取得或解析，依賴風險未知。"})
    threshold = config["caps"]["maintenance_below"]["score"]
    if maintenance < threshold:
        when = "最後推送時間不明" if days_since_push is None \
            else f"最後推送距今 {days_since_push} 天"
        risks.append({"type": "maintenance_risk", "level": "medium",
                      "detail": f"{when}，維護活躍度偏低。"})
    risks.sort(key=lambda r: RISK_RANK.get(r["level"], 0), reverse=True)
    return risks


def _tighter(current: str, candidate: str, order: List[str]) -> str:
    return candidate if order.index(candidate) > order.index(current) else current


def compute_cap(license_info: Dict[str, Any], dependency_risk_list: List[Dict[str, str]],
                dependency_status: str, maintenance: int,
                config: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    rules = (config or load_config())["caps"]
    order = list(rules["order"])
    cap = order[0]
    reasons: List[str] = []

    def apply(limit: str, reason: str) -> None:
        nonlocal cap
        if order.index(limit) > 0:
            reasons.append(f"{reason} → 上限 {limit}")
        cap = _tighter(cap, limit, order)

    apply(rules["license"][license_info["category"]],
          f"授權類別 {license_info['category']}"
          f"（{license_info.get('spdx_id') or 'unknown'}）")
    if maintenance < rules["maintenance_below"]["score"]:
        apply(rules["maintenance_below"]["cap"],
              f"維護活躍度 {maintenance} < {rules['maintenance_below']['score']}")
    if any(r["level"] == "high" for r in dependency_risk_list):
        apply(rules["dependency_risk_high"], "依賴風險 high")
    if dependency_status in UNKNOWN_DEPENDENCY_STATUSES:
        apply(rules["dependency_parsing_failed"], "依賴清單無法取得或解析")
    return cap, reasons
