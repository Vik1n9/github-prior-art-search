import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from . import search_github as gh
from .analyze import analyze_repository
from .common import ScriptFailure, load_skill_metadata, utc_now_iso
from .contract import input_warnings, normalize_query
from .score_candidates import rank_score, relevance_score

SCHEMA_VERSION = 3
PARTIAL_WARNING_TYPES = {"rate_limit", "search_failed", "search_skipped",
                         "tree_fetch_failed", "readme_fetch_failed",
                         "release_check_failed", "dependency_parsing_failed"}


class SearchContext:
    def __init__(self, input_data: Dict[str, Any], token: str,
                 config: Dict[str, Any], now_ts: float):
        self.input = input_data
        self.token = token
        self.config = config
        self.now_ts = now_ts
        self.min_stars = gh.effective_min_stars(input_data)
        self.max_age_days = gh.effective_max_age_days(input_data)
        self.per_component = int(input_data.get("candidates_per_component")
                                 or config["defaults"]["candidates_per_component"])
        self.rate_limited = False

    def stack_for(self, component: Dict[str, Any]) -> List[str]:
        stack = component.get("tech_stack")
        return list(stack) if stack is not None else list(self.input.get("tech_stack") or [])


def _run_queries(component: Dict[str, Any], queries: List[str], ctx: SearchContext
                 ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Dict[str, str]]]:
    hits: List[Tuple[str, Dict[str, Any]]] = []
    warnings: List[Dict[str, str]] = []
    for query in queries:
        if ctx.rate_limited:
            warnings.append({"type": "search_skipped", "component": component["id"],
                             "query": query, "detail": "先前查詢已觸發 rate limit，略過。"})
            continue
        items, error = gh.search_repositories(query, ctx.token, ctx.min_stars)
        if error:
            kind = "rate_limit" if error["kind"] == "rate_limit" else "search_failed"
            ctx.rate_limited = ctx.rate_limited or kind == "rate_limit"
            warnings.append({"type": kind, "component": component["id"],
                             "query": query, "detail": error["detail"]})
            continue
        hits.extend((query, item) for item in items)
    return hits, warnings


def _shortlist(component: Dict[str, Any], queries: List[str], ctx: SearchContext
               ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, str]]]:
    hits, warnings = _run_queries(component, queries, ctx)
    kept, discarded = gh.filter_repositories(
        [repo for _query, repo in hits], ctx.input.get("exclude_repos") or [],
        ctx.min_stars, ctx.max_age_days, ctx.now_ts)
    kept_names = {repo["full_name"] for repo in kept}
    merged = gh.merge_hits([(q, r) for q, r in hits if r.get("full_name") in kept_names])

    stack = ctx.stack_for(component)
    scored = []
    for repo, repo_queries in merged:
        prefilter = relevance_score(component["match_terms"], stack, repo, None,
                                    len(repo_queries), len(queries), ctx.config)
        scored.append({"repo": repo, "queries": repo_queries,
                       "prefilter_score": prefilter["score"]})
    scored.sort(key=lambda s: (s["prefilter_score"], len(s["queries"]),
                               s["repo"].get("stargazers_count", 0)), reverse=True)

    unique_discarded = {d["repository"]: d for d in discarded}
    stats = {
        "raw_results": len(hits),
        "unique_after_filter": len(merged),
        "discarded_unique": len(unique_discarded),
        "shortlisted": min(len(scored), ctx.per_component),
    }
    record = {"stats": stats,
              "discarded_sample": list(unique_discarded.values())[:20]}
    return record, scored[:ctx.per_component], warnings


def _analyze_all(repos: Dict[str, Dict[str, Any]], ctx: SearchContext
                 ) -> Dict[str, Tuple[Dict[str, Any], Optional[str]]]:
    workers = max(1, int(ctx.config["analysis"]["workers"]))
    names = sorted(repos)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda name: analyze_repository(
            repos[name], ctx.token, ctx.now_ts, ctx.config), names)
        return dict(zip(names, results))


def _component_record(component: Dict[str, Any], queries: List[str],
                      round_number: int, history: List[List[str]]) -> Dict[str, Any]:
    return {
        "id": component["id"],
        "name": component["name"],
        "purpose": component.get("purpose") or "",
        "must_have": component["must_have"],
        "match_terms": component["match_terms"],
        "tech_stack": component.get("tech_stack"),
        "search_queries": queries,
        "round": round_number,
        "query_history": history + [queries],
    }


def _search_components(components: List[Dict[str, Any]], ctx: SearchContext,
                       rounds: Dict[str, int], histories: Dict[str, List[List[str]]]
                       ) -> Tuple[List[Dict[str, Any]], Dict[str, Any],
                                  List[Dict[str, str]]]:
    records: List[Dict[str, Any]] = []
    shortlists: Dict[str, List[Dict[str, Any]]] = {}
    warnings: List[Dict[str, str]] = []
    for component in components:
        queries = [normalize_query(q) for q in component["search_queries"]]
        record = _component_record(component, queries, rounds[component["id"]],
                                   histories.get(component["id"], []))
        search_record, shortlist, search_warnings = _shortlist(component, queries, ctx)
        record.update(search_record)
        records.append(record)
        shortlists[component["id"]] = shortlist
        warnings.extend(search_warnings)

    to_analyze = {s["repo"]["full_name"]: s["repo"]
                  for shortlist in shortlists.values() for s in shortlist}
    analyzed = _analyze_all(to_analyze, ctx)

    for record, component in zip(records, components):
        candidates = []
        for entry in shortlists[component["id"]]:
            name = entry["repo"]["full_name"]
            facts, readme = analyzed[name]
            relevance = relevance_score(component["match_terms"],
                                        ctx.stack_for(component), entry["repo"], readme,
                                        len(entry["queries"]),
                                        len(record["search_queries"]), ctx.config)
            candidates.append({
                "repository": name,
                "rank_score": rank_score(relevance["score"], facts["scores"]["health"],
                                         ctx.config),
                "relevance": relevance,
                "prefilter_score": entry["prefilter_score"],
                "matched_queries": entry["queries"],
                "cap": facts["cap"],
            })
        candidates.sort(key=lambda c: c["rank_score"], reverse=True)
        record["candidates"] = candidates
        record["status"] = "has_candidates" if candidates else "no_candidates"

    repositories = {name: facts for name, (facts, _readme) in analyzed.items()}
    return records, repositories, warnings


def _previous_state(previous: Dict[str, Any], input_data: Dict[str, Any],
                    only: List[str], max_rounds: int
                    ) -> Tuple[Dict[str, int], Dict[str, List[List[str]]]]:
    if previous.get("schema_version") != SCHEMA_VERSION:
        raise ScriptFailure("既有 result.json 版本不符，請不帶 --only 重新執行。",
                            "invalid_previous")
    if previous.get("requirement") != input_data["requirement"]:
        raise ScriptFailure("requirement 與既有 result.json 不同；需求已變更時請不帶 "
                            "--only 重新執行。", "invalid_previous")
    previous_ids = [c["id"] for c in previous["components"]]
    input_ids = [c["id"] for c in input_data["components"]]
    if previous_ids != input_ids:
        raise ScriptFailure("--only 模式下組件清單（id 與順序）必須與既有 result.json 相同。",
                            "invalid_previous")
    unknown = [cid for cid in only if cid not in input_ids]
    if unknown:
        raise ScriptFailure(f"--only 指定了不存在的組件：{', '.join(unknown)}",
                            "invalid_input")

    rounds: Dict[str, int] = {}
    histories: Dict[str, List[List[str]]] = {}
    for component in previous["components"]:
        if component["id"] not in only:
            continue
        next_round = int(component["round"]) + 1
        if next_round > max_rounds:
            raise ScriptFailure(f"組件 {component['id']} 已達搜尋輪數上限 {max_rounds}，"
                                "請改判 build_in_house。", "max_rounds_exceeded")
        rounds[component["id"]] = next_round
        histories[component["id"]] = component["query_history"]
    return rounds, histories


def _status(components: List[Dict[str, Any]], repositories: Dict[str, Any],
            warnings: List[Dict[str, str]]) -> str:
    referenced = {c["repository"] for comp in components for c in comp["candidates"]}
    repo_warning_types = {w["type"] for name in referenced
                          for w in repositories[name]["warnings"]}
    all_types = repo_warning_types | {w["type"] for w in warnings}
    return "partial" if all_types & PARTIAL_WARNING_TYPES else "completed"


def run_search(input_data: Dict[str, Any], token: str, config: Dict[str, Any],
               previous: Optional[Dict[str, Any]] = None,
               only: Optional[List[str]] = None,
               now_ts: Optional[float] = None) -> Dict[str, Any]:
    started_at = utc_now_iso()
    ctx = SearchContext(input_data, token, config, time.time() if now_ts is None else now_ts)
    components = input_data["components"]

    if only:
        rounds, histories = _previous_state(previous or {}, input_data, only,
                                            int(config["search"]["max_rounds"]))
        targets = [c for c in components if c["id"] in only]
    else:
        rounds = {c["id"]: 1 for c in components}
        histories = {}
        targets = components

    records, repositories, warnings = _search_components(targets, ctx, rounds, histories)
    warnings = input_warnings({"components": targets}) + warnings

    if only and previous:
        fresh = {r["id"]: r for r in records}
        records = [fresh.get(c["id"], c) for c in previous["components"]]
        warnings = [w for w in previous["warnings"]
                    if w.get("component") not in fresh] + warnings
        for record in records:
            for candidate in record["candidates"]:
                name = candidate["repository"]
                if name not in repositories:
                    repositories[name] = previous["repositories"][name]

    skill = load_skill_metadata()
    return {
        "skill": skill["name"],
        "schema_version": SCHEMA_VERSION,
        "phase": "search",
        "status": _status(records, repositories, warnings),
        "execution": {
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "script_version": skill["version"],
            "rerun_components": list(only or []),
        },
        "requirement": input_data["requirement"],
        "tech_stack": input_data.get("tech_stack") or [],
        "filters": {
            "min_stars": ctx.min_stars,
            "last_push_within_days": ctx.max_age_days,
            "exclude_repos": input_data.get("exclude_repos") or [],
            "archived": "excluded",
            "disabled": "excluded",
        },
        "components": records,
        "repositories": dict(sorted(repositories.items())),
        "warnings": warnings,
    }
