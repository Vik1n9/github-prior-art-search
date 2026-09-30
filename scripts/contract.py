import re
from typing import Any, Dict, List, Optional

from .common import ScriptFailure, has_cjk, load_config

COMPONENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
DECISIONS_REUSE = ("adopt_as_dependency", "fork_and_modify", "use_as_template",
                   "reference_architecture_only")
VERDICTS = ("reuse", "build_in_house")
FITS = ("full", "partial")


def _is_str_list(value: Any, allow_empty: bool = False) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and \
        all(isinstance(x, str) and x.strip() for x in value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _validate_component(index: int, component: Any, errors: List[str],
                        search_cfg: Dict[str, Any]) -> None:
    where = f"components[{index}]"
    if not isinstance(component, dict):
        errors.append(f"{where} 必須是物件")
        return
    cid = component.get("id")
    if not isinstance(cid, str) or not COMPONENT_ID_RE.match(cid):
        errors.append(f"{where}.id 必須是小寫英數與連字號（最長 40 字元）")
    else:
        where = f"components[{cid}]"
    if not isinstance(component.get("name"), str) or not component["name"].strip():
        errors.append(f"{where}.name 必填")
    if component.get("purpose") is not None and not isinstance(component["purpose"], str):
        errors.append(f"{where}.purpose 必須是字串")
    for field in ("must_have", "match_terms", "search_queries"):
        if not _is_str_list(component.get(field)):
            errors.append(f"{where}.{field} 必須是非空字串陣列")
    if component.get("tech_stack") is not None and \
            not _is_str_list(component["tech_stack"], allow_empty=True):
        errors.append(f"{where}.tech_stack 必須是字串陣列")

    must_have = component.get("must_have")
    if _is_str_list(must_have) and \
            len({m.strip() for m in must_have}) != len(must_have):
        errors.append(f"{where}.must_have 不得重複")

    queries = component.get("search_queries")
    if not _is_str_list(queries):
        return
    normalized = [normalize_query(q) for q in queries]
    if len({q.lower() for q in normalized}) != len(normalized):
        errors.append(f"{where}.search_queries 不得重複")
    cap = int(search_cfg["max_queries_per_component"])
    if len(normalized) > cap:
        errors.append(f"{where}.search_queries 最多 {cap} 條（目前 {len(normalized)}）")
    max_len = int(search_cfg["max_query_length"])
    for query in normalized:
        if len(query) > max_len:
            errors.append(f"{where} 查詢超過 {max_len} 字元：{query[:40]}…")
        if "stars:" in query.lower():
            errors.append(f"{where} 查詢不得含 stars:，星數門檻由腳本附加：{query}")
        if re.search(r"topic:(\s|$)", query):
            errors.append(f"{where} 查詢的 topic: 後必須緊接 slug：{query}")


def validate_input(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ScriptFailure("輸入必須是 JSON 物件", "invalid_input")
    config = load_config()
    search_cfg = config["search"]
    errors: List[str] = []

    if not isinstance(data.get("requirement"), str) or not data["requirement"].strip():
        errors.append("requirement 必填：使用者需求原文")
    if data.get("tech_stack") is not None and \
            not _is_str_list(data["tech_stack"], allow_empty=True):
        errors.append("tech_stack 必須是字串陣列")
    if data.get("exclude_repos") is not None and \
            not _is_str_list(data["exclude_repos"], allow_empty=True):
        errors.append("exclude_repos 必須是字串陣列")
    for field in ("min_stars", "last_commit_within_days", "candidates_per_component"):
        value = data.get(field)
        if value is not None and (not _is_int(value) or value <= 0):
            errors.append(f"{field} 必須是正整數")
    per_component = data.get("candidates_per_component")
    limit = int(config["defaults"]["max_candidates_per_component"])
    if _is_int(per_component) and per_component > limit:
        errors.append(f"candidates_per_component 不得超過 {limit}")

    components = data.get("components")
    if not isinstance(components, list) or not components:
        errors.append("components 必填：由呼叫端把需求拆成功能組件，腳本不代為拆解")
        components = []
    max_components = int(search_cfg["max_components"])
    if len(components) > max_components:
        errors.append(f"components 最多 {max_components} 個（目前 {len(components)}）")
    for index, component in enumerate(components):
        _validate_component(index, component, errors, search_cfg)

    ids = [c.get("id") for c in components if isinstance(c, dict)]
    if len(set(ids)) != len(ids):
        errors.append("components[].id 不得重複")
    total = sum(len(c.get("search_queries") or []) for c in components
                if isinstance(c, dict) and isinstance(c.get("search_queries"), list))
    if total > int(search_cfg["max_total_queries"]):
        errors.append(f"全部查詢合計最多 {search_cfg['max_total_queries']} 條（目前 {total}）")

    if errors:
        raise ScriptFailure("輸入校驗失敗：\n- " + "\n- ".join(errors), "invalid_input")
    return data


def input_warnings(data: Dict[str, Any]) -> List[Dict[str, str]]:
    warnings = []
    for component in data["components"]:
        if all(has_cjk(term) for term in component["match_terms"]):
            warnings.append({
                "type": "match_terms_cjk_only", "component": component["id"],
                "detail": "match_terms 全為中日韓文字，對英文倉庫幾乎無法比對；"
                          "相關度可能被低估。"})
    return warnings


def _check_text(value: Any, limit: int, where: str, errors: List[str],
                required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where} 必須是非空字串")
    elif len(value) > limit:
        errors.append(f"{where} 超過 {limit} 字元（目前 {len(value)}）")


def _check_decision(decision: Any, repo: str, caps: Dict[str, str],
                    order: List[str], where: str, errors: List[str]) -> None:
    if decision not in DECISIONS_REUSE:
        errors.append(f"{where}.decision 必須是 {'/'.join(DECISIONS_REUSE)} 之一")
        return
    cap = caps.get(repo)
    if cap and order.index(decision) < order.index(cap):
        errors.append(f"{where}.decision={decision} 高於腳本上限 {cap}（{repo}）")


def _check_selected(selected: Any, component: Dict[str, Any], caps: Dict[str, str],
                    order: List[str], where: str, errors: List[str],
                    limits: Dict[str, Any]) -> None:
    if not isinstance(selected, dict):
        errors.append(f"{where}.selected 必須是物件")
        return
    candidates = {c["repository"] for c in component["candidates"]}
    repo = selected.get("repository")
    if repo not in candidates:
        errors.append(f"{where}.selected.repository 不在此組件的候選清單中：{repo}")
    _check_decision(selected.get("decision"), repo, caps, order,
                    f"{where}.selected", errors)

    fit = selected.get("fit")
    if fit not in FITS:
        errors.append(f"{where}.selected.fit 必須是 full 或 partial")
    covered = selected.get("covered")
    gaps = selected.get("gaps")
    if not _is_str_list(covered, allow_empty=True) or \
            not _is_str_list(gaps, allow_empty=True):
        errors.append(f"{where}.selected.covered 與 gaps 必須是字串陣列")
    else:
        must_have = set(component["must_have"])
        if set(covered) & set(gaps):
            errors.append(f"{where}.selected.covered 與 gaps 不得重疊")
        if set(covered) | set(gaps) != must_have:
            errors.append(f"{where}.selected.covered ∪ gaps 必須正好等於 must_have："
                          f"{sorted(must_have)}")
        if not covered:
            errors.append(f"{where}.selected.covered 不得為空；一項都不符合應改判 build_in_house")
        if fit == "full" and gaps:
            errors.append(f"{where}.selected.fit=full 時 gaps 必須為空")
        if fit == "partial" and not gaps:
            errors.append(f"{where}.selected.fit=partial 時 gaps 不得為空")

    evidence = selected.get("evidence")
    if not _is_str_list(evidence):
        errors.append(f"{where}.selected.evidence 必須是非空字串陣列")
    else:
        if len(evidence) > limits["max_evidence_items"]:
            errors.append(f"{where}.selected.evidence 最多 {limits['max_evidence_items']} 條")
        for i, item in enumerate(evidence):
            _check_text(item, limits["max_evidence_chars"],
                        f"{where}.selected.evidence[{i}]", errors)
    _check_text(selected.get("rationale"), limits["max_rationale_chars"],
                f"{where}.selected.rationale", errors)


def _check_alternatives(alternatives: Any, component: Dict[str, Any],
                        selected_repo: Optional[str], caps: Dict[str, str],
                        order: List[str], where: str, errors: List[str],
                        limits: Dict[str, Any]) -> None:
    if alternatives is None:
        return
    if not isinstance(alternatives, list):
        errors.append(f"{where}.alternatives 必須是陣列")
        return
    if len(alternatives) > limits["max_alternatives"]:
        errors.append(f"{where}.alternatives 最多 {limits['max_alternatives']} 個")
    candidates = {c["repository"] for c in component["candidates"]}
    for i, alt in enumerate(alternatives):
        at = f"{where}.alternatives[{i}]"
        if not isinstance(alt, dict):
            errors.append(f"{at} 必須是物件")
            continue
        repo = alt.get("repository")
        if repo not in candidates:
            errors.append(f"{at}.repository 不在此組件的候選清單中：{repo}")
        elif repo == selected_repo:
            errors.append(f"{at}.repository 與 selected 重複")
        _check_decision(alt.get("decision"), repo, caps, order, at, errors)
        _check_text(alt.get("note"), limits["max_rationale_chars"], f"{at}.note", errors)


def validate_assessment(data: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config()
    limits = config["assessment"]
    order = list(config["caps"]["order"])
    caps = {name: repo["cap"] for name, repo in result["repositories"].items()}
    components = {c["id"]: c for c in result["components"]}
    errors: List[str] = []

    if not isinstance(data, dict):
        raise ScriptFailure("assessment 必須是 JSON 物件", "invalid_assessment")

    entries = data.get("components")
    if not isinstance(entries, list):
        errors.append("components 必須是陣列")
        entries = []
    seen: List[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"components[{index}] 必須是物件")
            continue
        cid = entry.get("id")
        where = f"components[{cid}]"
        if cid not in components:
            errors.append(f"components[{index}].id 不存在於 result.json：{cid}")
            continue
        seen.append(cid)
        component = components[cid]
        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{where}.verdict 必須是 reuse 或 build_in_house")
            continue
        if verdict == "reuse":
            if not component["candidates"]:
                errors.append(f"{where} 沒有候選，verdict 只能是 build_in_house")
                continue
            _check_selected(entry.get("selected"), component, caps, order, where,
                            errors, limits)
            selected_repo = (entry.get("selected") or {}).get("repository")
        else:
            if entry.get("selected") is not None:
                errors.append(f"{where}.verdict=build_in_house 時不得有 selected")
            _check_text(entry.get("rationale"), limits["max_rationale_chars"],
                        f"{where}.rationale", errors)
            selected_repo = None
        _check_alternatives(entry.get("alternatives"), component, selected_repo,
                            caps, order, where, errors, limits)

    missing = [cid for cid in components if cid not in seen]
    if missing:
        errors.append(f"缺少組件評估：{', '.join(missing)}")
    duplicated = sorted({cid for cid in seen if seen.count(cid) > 1})
    if duplicated:
        errors.append(f"組件評估重複：{', '.join(duplicated)}")

    _check_text(data.get("executive_summary"), limits["max_summary_chars"],
                "executive_summary", errors)
    observations = data.get("notable_observations", [])
    if not _is_str_list(observations, allow_empty=True):
        errors.append("notable_observations 必須是字串陣列")
    elif len(observations) > limits["max_observations"]:
        errors.append(f"notable_observations 最多 {limits['max_observations']} 條")

    if errors:
        raise ScriptFailure("assessment 校驗失敗：\n- " + "\n- ".join(errors),
                            "invalid_assessment")
    return data
