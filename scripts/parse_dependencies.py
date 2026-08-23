# -*- coding: utf-8 -*-
"""依賴解析（§12）：清單偵測、解析、統計與風險標記全部由腳本執行。"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

from common import load_config


def is_pinned_version(version: str) -> bool:
    """^、~、*、latest、next、範圍與空值皆視為未固定（§19）。"""
    if not version:
        return False
    version = str(version).strip()
    if not version or version.startswith(("^", "~", ">=", "<=", ">", "<")):
        return False
    if version.lower() in ("latest", "next", "*"):
        return False
    if "," in version or " || " in version or "-" == version[:1]:
        return False
    # x-range：1.x / 1.2.x
    if re.search(r"\.x(\.|$)", version.lower()):
        return False
    return bool(re.match(r"^v?\d", version))


# ---------------------------------------------------------------------------
# 各生態系解析器：回傳 [{name, version, type}]
# ---------------------------------------------------------------------------

def parse_package_json(content: str) -> Dict[str, List[Dict[str, str]]]:
    data = json.loads(content)
    result: Dict[str, List[Dict[str, str]]] = {"runtime": [], "dev": []}
    for dep_type, key in (("runtime", "dependencies"), ("dev", "devDependencies")):
        section = data.get(key) or {}
        for name, version in section.items():
            result[dep_type].append({"name": name, "version": str(version)})
    return result


_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\[\]-]+)\s*(===?|~=|>=|<=|!=|>|<)?\s*([^;,\s]*)")


def parse_requirements_txt(content: str) -> Dict[str, List[Dict[str, str]]]:
    deps: List[Dict[str, str]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = _REQ_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1).split("[")[0]
        operator = match.group(2)
        raw_version = match.group(3)
        # 僅 == 視為固定；== 後接萬用字元（1.*）仍視為未固定
        pinned = operator == "==" and "*" not in raw_version and bool(raw_version)
        version = f"{operator}{raw_version}" if operator else ""
        deps.append({"name": name, "version": version, "_pinned_override": pinned})
    return {"runtime": deps, "dev": []}


def parse_pyproject_toml(content: str) -> Dict[str, List[Dict[str, str]]]:
    """輕量解析 [project].dependencies 與 [tool.poetry.dependencies]（不引第三方 toml 依賴）。"""
    runtime: List[Dict[str, str]] = []
    dev: List[Dict[str, str]] = []

    in_project_deps = False
    in_poetry_deps = False
    in_poetry_group_dev = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.strip("[]")
            in_project_deps = section == "project"
            in_poetry_deps = section.startswith("tool.poetry.dependencies")
            in_poetry_group_dev = section.startswith("tool.poetry.group.dev.dependencies") \
                or section == "tool.poetry.dev-dependencies"
            continue
        if not in_project_deps and not in_poetry_deps and not in_poetry_group_dev:
            continue
        if not stripped or stripped.startswith("#"):
            continue

        if in_project_deps and stripped.startswith("dependencies"):
            inner = stripped.split("=", 1)[1] if "=" in stripped else ""
            for item in re.findall(r'"([^"]+)"', inner):
                parsed = _pep508_to_dep(item, "runtime")
                if parsed:
                    runtime.append(parsed)
        elif (in_poetry_deps or in_poetry_group_dev) and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            value = stripped.split("=", 1)[1].strip()
            version_match = re.search(r'["\']?([^"\'}]+)["\']?', value)
            version = version_match.group(1).strip() if version_match else ""
            target = dev if in_poetry_group_dev else runtime
            target.append({
                "name": name,
                "version": version,
                "_pinned_override": is_pinned_version(version),
            })
    return {"runtime": runtime, "dev": dev}


def _pep508_to_dep(requirement: str, dep_type: str) -> Optional[Dict[str, str]]:
    match = re.match(r"^([A-Za-z0-9_.\[\]-]+)\s*(.*)$", requirement.strip())
    if not match:
        return None
    name, spec = match.group(1).split("[")[0], match.group(2)
    pinned = spec.startswith("==") and "*" not in spec
    return {"name": name, "version": spec, "_pinned_override": pinned}


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


def parse_cargo_toml(content: str) -> Dict[str, List[Dict[str, str]]]:
    runtime: List[Dict[str, str]] = []
    dev: List[Dict[str, str]] = []
    current = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.strip("[]")
            current = None
            if section in ("dependencies", "dev-dependencies", "build-dependencies"):
                current = runtime if section == "dependencies" else dev
            continue
        if current is None or not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*(.+)$', stripped)
        if not match:
            continue
        name, raw = match.group(1), match.group(2)
        version_match = re.search(r'"([^"]+)"', raw)
        version = version_match.group(1) if version_match else ""
        current.append({"name": name, "version": version})
    return {"runtime": runtime, "dev": []}


def parse_pom_xml(content: str) -> Dict[str, List[Dict[str, str]]]:
    deps: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(re.sub(r"&(?![a-zA-Z]+;)", "&amp;", content))
    except ET.ParseError:
        return {"runtime": [], "dev": []}
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    containers = root.findall(".//m:dependencies", ns) or root.findall(".//dependencies")
    seen_container = set()
    for container in containers:
        if id(container) in seen_container:
            continue
        seen_container.add(id(container))
        for dep in list(container):
            tag = lambda el: el.tag.split("}")[-1]
            group = artifact = version = ""
            for child in dep:
                local = tag(child)
                text = (child.text or "").strip()
                if local == "groupId":
                    group = text
                elif local == "artifactId":
                    artifact = text
                elif local == "version":
                    version = text
            if artifact:
                deps.append({"name": f"{group}:{artifact}" if group else artifact,
                             "version": version})
    return {"runtime": deps, "dev": []}


_GRADLE_DEP_RE = re.compile(
    r"""(implementation|api|compile|runtimeOnly|compileOnly|testImplementation)\s*\(?
        \s*['"]([^:'"]+):([^:'"]+):([^'"]+)['"]""", re.VERBOSE)


def parse_gradle(content: str) -> Dict[str, List[Dict[str, str]]]:
    runtime: List[Dict[str, str]] = []
    dev: List[Dict[str, str]] = []
    for match in _GRADLE_DEP_RE.finditer(content):
        scope, group, name, version = match.group(1), match.group(2), match.group(3), match.group(4)
        entry = {"name": f"{group}:{name}", "version": version}
        if scope.startswith("test"):
            dev.append(entry)
        else:
            runtime.append(entry)
    return {"runtime": runtime, "dev": []}


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

PARSE_FAILED = "dependency_parsing_failed"


# ---------------------------------------------------------------------------
# 清單偵測與彙總
# ---------------------------------------------------------------------------

def find_manifests(paths: List[str]) -> Dict[str, List[str]]:
    manifests: Dict[str, List[str]] = {}
    manifest_map = load_config()["dependency_manifests"]
    top_level = {p for p in paths if "/" not in p}
    for ecosystem, spec in manifest_map.items():
        found = sorted(top_level & set(spec.get("files", [])))
        if found:
            manifests[ecosystem] = found
    return manifests


def find_lockfiles(paths: List[str]) -> List[str]:
    manifest_map = load_config()["dependency_manifests"]
    all_lockfiles: List[str] = []
    for spec in manifest_map.values():
        all_lockfiles.extend(spec.get("lockfiles", []))
    top_level = {p for p in paths if "/" not in p}
    return sorted(top_level & set(all_lockfiles))


def build_dependency_list(manifests: Dict[str, List[str]],
                          contents: Dict[str, str]) -> List[Dict[str, Any]]:
    dependencies: List[Dict[str, Any]] = []
    for ecosystem, files in manifests.items():
        for file_name in files:
            content = contents.get(file_name)
            if content is None:
                continue
            parser = PARSERS.get((ecosystem, file_name))
            if parser is None:
                continue
            try:
                parsed = parser(content)
            except Exception:
                raise ValueError(f"{file_name} 解析失敗")
            for dep_type, entries in parsed.items():
                for entry in entries:
                    override = entry.pop("_pinned_override", None)
                    version = entry.get("version", "")
                    pinned = override if override is not None else is_pinned_version(version)
                    dependencies.append({
                        "ecosystem": ecosystem,
                        "name": entry["name"],
                        "version": version,
                        "type": dep_type,
                        "pinned": bool(pinned),
                    })
    return dependencies


def summarize_dependencies(dependencies: List[Dict[str, Any]], lockfiles: List[str],
                           manifests: Dict[str, List[str]]) -> Dict[str, Any]:
    runtime = [d for d in dependencies if d["type"] == "runtime"]
    dev = [d for d in dependencies if d["type"] == "dev"]
    unpinned = [d for d in dependencies if not d["pinned"]]
    return {
        "manifests_found": sorted(manifests.keys()),
        "manifest_files": sorted(f for files in manifests.values() for f in files),
        "lockfiles_found": lockfiles,
        "lockfile_present": len(lockfiles) > 0,
        "runtime_count": len(runtime),
        "dev_count": len(dev),
        "total_count": len(dependencies),
        "unpinned_count": len(unpinned),
        "details": dependencies,
    }


def dependency_risks(summary: Dict[str, Any], config: Optional[Dict[str, Any]] = None
                     ) -> List[Dict[str, str]]:
    cfg = config or load_config()
    rules = cfg["dependency_risk_rules"]
    risks: List[Dict[str, str]] = []

    total_rule = rules["high_total_dependencies"]
    if summary["total_count"] > int(total_rule["threshold"]):
        risks.append({
            "type": "dependency_risk",
            "level": total_rule["level"],
            "detail": f"依賴總數 {summary['total_count']} 超過門檻 {total_rule['threshold']}。",
        })

    unpinned_rule = rules["high_unpinned_dependencies"]
    if summary["unpinned_count"] > int(unpinned_rule["threshold"]):
        risks.append({
            "type": "dependency_risk",
            "level": unpinned_rule["level"],
            "detail": f"未固定版本依賴 {summary['unpinned_count']} 筆超過門檻 {unpinned_rule['threshold']}。",
        })

    no_lockfile_level = rules["no_lockfile"]["level"]
    if not summary["lockfile_present"] and summary["total_count"] > 0:
        risks.append({
            "type": "dependency_risk",
            "level": no_lockfile_level,
            "detail": "未偵測到 lockfile，版本重現性無法保證。",
        })

    return risks


def analyze_dependencies(paths: List[str],
                         fetch_content: Callable[[str], Optional[str]]
                         ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """回傳 (dependencies 物件或 None, warnings)。解析失敗時標記 partial。"""
    warnings: List[Dict[str, str]] = []
    manifests = find_manifests(paths)
    lockfiles = find_lockfiles(paths)

    if not manifests:
        return {
            "manifests_found": [],
            "manifest_files": [],
            "lockfiles_found": lockfiles,
            "lockfile_present": len(lockfiles) > 0,
            "runtime_count": 0,
            "dev_count": 0,
            "total_count": 0,
            "unpinned_count": 0,
            "details": [],
        }, warnings

    contents: Dict[str, str] = {}
    failed_files: List[str] = []
    for ecosystem, files in manifests.items():
        for file_name in files:
            content = fetch_content(file_name)
            if content is None:
                failed_files.append(file_name)
            else:
                contents[file_name] = content

    if failed_files:
        warnings.append({
            "type": PARSE_FAILED,
            "detail": f"無法取得依賴清單內容：{', '.join(failed_files)}",
        })
        if not contents:
            return None, warnings

    try:
        dependencies = build_dependency_list(manifests, contents)
    except ValueError as exc:
        warnings.append({"type": PARSE_FAILED, "detail": str(exc)})
        return None, warnings

    summary = summarize_dependencies(dependencies, lockfiles, manifests)
    return summary, warnings
