import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

from .common import load_config

PARSE_FAILED = "dependency_parsing_failed"

_RANGE_PREFIXES = ("^", "~", ">=", "<=", ">", "<", "-")
_WILDCARD_VERSIONS = ("latest", "next", "*")
_X_RANGE_RE = re.compile(r"\.x(\.|$)")
_NUMERIC_START_RE = re.compile(r"^v?\d")


def _is_range_operator(version: str) -> bool:
    return version.startswith(_RANGE_PREFIXES) or "," in version or " || " in version


def _is_wildcard(version: str) -> bool:
    return version.lower() in _WILDCARD_VERSIONS


def _is_x_range(version: str) -> bool:
    return bool(_X_RANGE_RE.search(version.lower()))


def is_pinned_version(version: str) -> bool:
    version = str(version or "").strip()
    if not version:
        return False
    if _is_range_operator(version) or _is_wildcard(version) or _is_x_range(version):
        return False
    return bool(_NUMERIC_START_RE.match(version))


def parse_package_json(content: str) -> Dict[str, List[Dict[str, str]]]:
    data = json.loads(content)
    parsed: Dict[str, List[Dict[str, str]]] = {"runtime": [], "dev": []}
    for dep_type, key in (("runtime", "dependencies"), ("dev", "devDependencies")):
        for name, version in (data.get(key) or {}).items():
            parsed[dep_type].append({"name": name, "version": str(version)})
    return parsed


_REQ_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_.\[\]-]+)\s*(===?|~=|>=|<=|!=|>|<)?\s*([^;,\s]*)")


def parse_requirements_txt(content: str) -> Dict[str, List[Dict[str, str]]]:
    deps: List[Dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = _REQ_LINE_RE.match(line)
        if not match:
            continue
        name, operator, raw_version = match.group(1), match.group(2), match.group(3)
        deps.append({
            "name": name.split("[")[0],
            "version": f"{operator}{raw_version}" if operator else "",
            "_pinned_override": operator == "==" and bool(raw_version)
            and "*" not in raw_version,
        })
    return {"runtime": deps, "dev": []}


def _pep508_to_dep(requirement: str) -> Optional[Dict[str, Any]]:
    match = re.match(r"^([A-Za-z0-9_.\[\]-]+)\s*(.*)$", requirement.strip())
    if not match:
        return None
    spec = match.group(2)
    return {
        "name": match.group(1).split("[")[0],
        "version": spec,
        "_pinned_override": spec.startswith("==") and "*" not in spec,
    }


def parse_pyproject_toml(content: str) -> Dict[str, List[Dict[str, str]]]:
    runtime: List[Dict[str, Any]] = []
    dev: List[Dict[str, Any]] = []
    in_project = in_poetry_runtime = in_poetry_dev = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.strip("[]")
            in_project = section == "project"
            in_poetry_runtime = section.startswith("tool.poetry.dependencies")
            in_poetry_dev = section.startswith("tool.poetry.group.dev.dependencies") \
                or section == "tool.poetry.dev-dependencies"
            continue
        if not stripped or stripped.startswith("#"):
            continue

        if in_project and stripped.startswith("dependencies"):
            inner = stripped.split("=", 1)[1] if "=" in stripped else ""
            for item in re.findall(r'"([^"]+)"', inner):
                parsed = _pep508_to_dep(item)
                if parsed:
                    runtime.append(parsed)
        elif (in_poetry_runtime or in_poetry_dev) and "=" in stripped:
            name, _, value = stripped.partition("=")
            version_match = re.search(r'["\']?([^"\'}]+)["\']?', value.strip())
            version = version_match.group(1).strip() if version_match else ""
            target = dev if in_poetry_dev else runtime
            target.append({"name": name.strip(), "version": version,
                           "_pinned_override": is_pinned_version(version)})
    return {"runtime": runtime, "dev": dev}


def parse_go_mod(content: str) -> Dict[str, List[Dict[str, str]]]:
    deps: List[Dict[str, str]] = []
    in_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        if stripped.startswith("require "):
            stripped = stripped[len("require "):].strip()
        elif not in_block:
            continue
        parts = stripped.split()
        if len(parts) >= 2 and not parts[0].startswith("//"):
            deps.append({"name": parts[0], "version": parts[1]})
    return {"runtime": deps, "dev": []}


_CARGO_DEP_RE = re.compile(r'^([A-Za-z0-9_-]+)\s*=\s*(.+)$')
_CARGO_SECTIONS = {"dependencies": "runtime", "dev-dependencies": "dev",
                   "build-dependencies": "dev"}


def parse_cargo_toml(content: str) -> Dict[str, List[Dict[str, str]]]:
    parsed: Dict[str, List[Dict[str, str]]] = {"runtime": [], "dev": []}
    target: Optional[List[Dict[str, str]]] = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            dep_type = _CARGO_SECTIONS.get(stripped.strip("[]"))
            target = parsed[dep_type] if dep_type else None
            continue
        if target is None or not stripped or stripped.startswith("#"):
            continue
        match = _CARGO_DEP_RE.match(stripped)
        if not match:
            continue
        version_match = re.search(r'"([^"]+)"', match.group(2))
        target.append({"name": match.group(1),
                       "version": version_match.group(1) if version_match else ""})
    return parsed


def _local_tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1]


def parse_pom_xml(content: str) -> Dict[str, List[Dict[str, str]]]:
    try:
        root = ET.fromstring(re.sub(r"&(?![a-zA-Z]+;)", "&amp;", content))
    except ET.ParseError:
        return {"runtime": [], "dev": []}

    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    containers = root.findall(".//m:dependencies", namespace) or \
        root.findall(".//dependencies")

    deps: List[Dict[str, str]] = []
    for container in containers:
        for dependency in list(container):
            fields = {_local_tag(child): (child.text or "").strip()
                      for child in dependency}
            artifact = fields.get("artifactId", "")
            if not artifact:
                continue
            group = fields.get("groupId", "")
            deps.append({"name": f"{group}:{artifact}" if group else artifact,
                         "version": fields.get("version", "")})
    return {"runtime": deps, "dev": []}


_GRADLE_DEP_RE = re.compile(
    r"""(implementation|api|compile|runtimeOnly|compileOnly|testImplementation)\s*\(?
        \s*['"]([^:'"]+):([^:'"]+):([^'"]+)['"]""", re.VERBOSE)


def parse_gradle(content: str) -> Dict[str, List[Dict[str, str]]]:
    parsed: Dict[str, List[Dict[str, str]]] = {"runtime": [], "dev": []}
    for match in _GRADLE_DEP_RE.finditer(content):
        scope, group, name, version = match.groups()
        dep_type = "dev" if scope.startswith("test") else "runtime"
        parsed[dep_type].append({"name": f"{group}:{name}", "version": version})
    return parsed


PARSERS = {
    ("npm", "package.json"): parse_package_json,
    ("python", "requirements.txt"): parse_requirements_txt,
    ("python", "pyproject.toml"): parse_pyproject_toml,
    ("go", "go.mod"): parse_go_mod,
    ("rust", "Cargo.toml"): parse_cargo_toml,
    ("java", "pom.xml"): parse_pom_xml,
    ("java", "build.gradle"): parse_gradle,
    ("java", "build.gradle.kts"): parse_gradle,
}


def _top_level(paths: List[str]) -> set:
    return {path for path in paths if "/" not in path}


def find_manifests(paths: List[str]) -> Dict[str, List[str]]:
    top_level = _top_level(paths)
    manifests: Dict[str, List[str]] = {}
    for ecosystem, spec in load_config()["dependency_manifests"].items():
        found = sorted(top_level & set(spec.get("files", [])))
        if found:
            manifests[ecosystem] = found
    return manifests


def find_lockfiles(paths: List[str]) -> List[str]:
    known: set = set()
    for spec in load_config()["dependency_manifests"].values():
        known.update(spec.get("lockfiles", []))
    return sorted(_top_level(paths) & known)


def build_dependency_list(manifests: Dict[str, List[str]],
                          contents: Dict[str, str]) -> List[Dict[str, Any]]:
    dependencies: List[Dict[str, Any]] = []
    for ecosystem, files in manifests.items():
        for file_name in files:
            content = contents.get(file_name)
            parser = PARSERS.get((ecosystem, file_name))
            if content is None or parser is None:
                continue
            try:
                parsed = parser(content)
            except Exception:
                raise ValueError(f"{file_name} 解析失敗")
            for dep_type, entries in parsed.items():
                for entry in entries:
                    override = entry.pop("_pinned_override", None)
                    version = entry.get("version", "")
                    dependencies.append({
                        "ecosystem": ecosystem,
                        "name": entry["name"],
                        "version": version,
                        "type": dep_type,
                        "pinned": bool(override if override is not None
                                       else is_pinned_version(version)),
                    })
    return dependencies


def summarize_dependencies(dependencies: List[Dict[str, Any]], lockfiles: List[str],
                           manifests: Dict[str, List[str]],
                           status: str = "parsed",
                           detail_limit: Optional[int] = None) -> Dict[str, Any]:
    limit = int(load_config()["analysis"]["dependency_detail_limit"]) \
        if detail_limit is None else detail_limit
    return {
        "status": status,
        "manifests_found": sorted(manifests.keys()),
        "manifest_files": sorted(f for files in manifests.values() for f in files),
        "lockfiles_found": lockfiles,
        "lockfile_present": bool(lockfiles),
        "runtime_count": sum(1 for d in dependencies if d["type"] == "runtime"),
        "dev_count": sum(1 for d in dependencies if d["type"] == "dev"),
        "total_count": len(dependencies),
        "unpinned_count": sum(1 for d in dependencies if not d["pinned"]),
        "details": dependencies[:limit],
        "details_truncated": len(dependencies) > limit,
    }


def dependency_risks(summary: Dict[str, Any],
                     config: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    if summary.get("status") != "parsed":
        return []
    risks: List[Dict[str, str]] = []
    flagged_kinds: set = set()
    for rule in (config or load_config())["dependency_risk_rules"]:
        kind = rule["kind"]
        if kind in flagged_kinds:
            continue
        if kind == "total" and summary["total_count"] > int(rule["threshold"]):
            detail = f"依賴總數 {summary['total_count']} 超過門檻 {rule['threshold']}。"
        elif kind == "unpinned" and summary["unpinned_count"] > int(rule["threshold"]):
            detail = (f"未固定版本依賴 {summary['unpinned_count']} 筆"
                      f"超過門檻 {rule['threshold']}。")
        elif kind == "no_lockfile" and not summary["lockfile_present"] \
                and summary["total_count"] > 0:
            detail = "未偵測到 lockfile，版本重現性無法保證。"
        else:
            continue
        flagged_kinds.add(kind)
        risks.append({"type": "dependency_risk", "level": rule["level"],
                      "detail": detail})
    return risks


def analyze_dependencies(paths: List[str],
                         fetch_content: Callable[[str], Tuple[Optional[str],
                                                              Optional[Dict[str, str]]]]
                         ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    manifests = find_manifests(paths)
    lockfiles = find_lockfiles(paths)

    if not manifests:
        return summarize_dependencies([], lockfiles, {}, "no_manifest"), warnings

    contents: Dict[str, str] = {}
    failed_files: List[str] = []
    for files in manifests.values():
        for file_name in files:
            content, _error = fetch_content(file_name)
            if content is None:
                failed_files.append(file_name)
            else:
                contents[file_name] = content

    if failed_files:
        warnings.append({"type": PARSE_FAILED,
                         "detail": f"無法取得依賴清單內容：{', '.join(failed_files)}"})
        if not contents:
            return summarize_dependencies([], lockfiles, manifests, "failed"), warnings

    try:
        dependencies = build_dependency_list(manifests, contents)
    except ValueError as exc:
        warnings.append({"type": PARSE_FAILED, "detail": str(exc)})
        return summarize_dependencies([], lockfiles, manifests, "failed"), warnings

    return summarize_dependencies(dependencies, lockfiles, manifests), warnings
