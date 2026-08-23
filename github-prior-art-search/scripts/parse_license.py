# -*- coding: utf-8 -*-
"""授權解析（§11）：分類、評分與動作全部由腳本決定，不由模型判定。"""
from typing import Any, Dict, List, Optional

LICENSE_FILE_CANDIDATES = (
    "license", "license.txt", "license.md", "copying", "copying.txt",
)


def normalize_spdx(spdx_id: Optional[str]) -> Optional[str]:
    if not spdx_id:
        return None
    value = str(spdx_id).strip()
    if not value or value.upper() in ("NOASSERTION", "OTHER", "NONE"):
        return None
    return value


def find_license_file(paths: List[str]) -> Optional[str]:
    for path in paths:
        parts = path.split("/")
        if len(parts) == 1 and parts[0].lower() in LICENSE_FILE_CANDIDATES:
            return path
    return None


def classify_license(spdx_id: Optional[str], config: Dict[str, Any]) -> str:
    """回傳 preferred | review_required | high_risk | unknown。"""
    policy = config["license_policy"]
    normalized = normalize_spdx(spdx_id)
    if normalized is None:
        return "unknown"
    upper = normalized.upper()
    for category in ("preferred", "review_required", "high_risk"):
        if any(upper == str(x).upper() for x in policy.get(category, [])):
            return category
    # 政策清單未列出的有效 SPDX：視為 review_required（保守處理）
    return "review_required"


def license_fit_score(category: str, config: Dict[str, Any]) -> int:
    return int(config["license_policy"]["scores"][category])


def license_action(category: str, config: Dict[str, Any]) -> str:
    return config["license_policy"]["actions"][category]


def license_risk_level(category: str, config: Dict[str, Any]) -> str:
    return config["license_policy"]["risk_levels"][category]


def analyze_license(metadata: Dict[str, Any], file_paths: List[str],
                    config: Dict[str, Any]) -> Dict[str, Any]:
    """優先使用 API 的 license.spdx_id；無則標記 unknown（不猜測檔案內容）。"""
    api_license = (metadata.get("license") or {}).get("spdx_id")
    source = "api_field"
    spdx = normalize_spdx(api_license)

    if spdx is None and find_license_file(file_paths):
        # 存在授權檔但 API 未識別：標記 NOASSERTION → unknown，不得由模型推測內容
        source = "license_file_unparsed"

    category = classify_license(spdx, config)
    return {
        "spdx_id": spdx,
        "source": source,
        "category": category,
        "license_fit_score": license_fit_score(category, config),
        "action": license_action(category, config),
        "risk_level": license_risk_level(category, config),
    }
