from typing import Any, Dict, List, Optional

LICENSE_FILE_CANDIDATES = ("license", "license.txt", "license.md",
                           "copying", "copying.txt")
UNRECOGNIZED_SPDX = ("NOASSERTION", "OTHER", "NONE")
CATEGORIES = ("preferred", "review_required", "high_risk")


def normalize_spdx(spdx_id: Optional[str]) -> Optional[str]:
    if not spdx_id:
        return None
    value = str(spdx_id).strip()
    if not value or value.upper() in UNRECOGNIZED_SPDX:
        return None
    return value


def find_license_file(paths: List[str]) -> Optional[str]:
    for path in paths:
        if "/" not in path and path.lower() in LICENSE_FILE_CANDIDATES:
            return path
    return None


def classify_license(spdx_id: Optional[str], config: Dict[str, Any]) -> str:
    normalized = normalize_spdx(spdx_id)
    if normalized is None:
        return "unknown"
    policy = config["license_policy"]
    upper = normalized.upper()
    for category in CATEGORIES:
        if any(upper == str(listed).upper() for listed in policy.get(category, [])):
            return category
    return "review_required"


def license_fit_score(category: str, config: Dict[str, Any]) -> int:
    return int(config["license_policy"]["scores"][category])


def license_action(category: str, config: Dict[str, Any]) -> str:
    return config["license_policy"]["actions"][category]


def license_risk_level(category: str, config: Dict[str, Any]) -> str:
    return config["license_policy"]["risk_levels"][category]


def analyze_license(metadata: Dict[str, Any], file_paths: List[str],
                    config: Dict[str, Any]) -> Dict[str, Any]:
    spdx = normalize_spdx((metadata.get("license") or {}).get("spdx_id"))
    source = "api_field"
    if spdx is None and find_license_file(file_paths):
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
