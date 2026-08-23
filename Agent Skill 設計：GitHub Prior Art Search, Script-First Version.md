

---

# Agent Skill 設計：GitHub Prior Art Search, Script-First Version

## 1. 技能基本資訊

```yaml
skill_name: github_prior_art_search
display_name: GitHub 先行調研與重用檢查
version: 1.1.0
execution_mode: script_first
model_role: assist_only
```

---

## 2. 設計原則

```yaml
principles:
  - 所有硬性條件由腳本判斷
  - 星數低於 100 直接忽略
  - 授權風險由腳本標記，不由模型判定
  - 依賴清單由腳本解析並寫入輸出
  - 模型不得產生最終採用結論
  - 模型僅能針對腳本結果產生文字摘要
  - 所有腳本輸出必須可重現
  - 若腳本無法取得資料，必須明確標記 partial 或 failed
```

---

## 3. 腳本與模型職責切分

| 項目            | 腳本負責 | 模型負責 |
| ------------- | ----:| ----:|
| 輸入校验          | 是    | 否    |
| 搜尋關鍵字生成       | 主要   | 可選補充 |
| GitHub API 查詢 | 是    | 否    |
| 星數過濾          | 是    | 否    |
| 封存專案過濾        | 是    | 否    |
| 授權條款解析        | 是    | 否    |
| 依賴解析          | 是    | 否    |
| 更新時間判斷        | 是    | 否    |
| 評分            | 是    | 否    |
| 候選專案排序        | 是    | 否    |
| 風險標記          | 是    | 否    |
| 最終採用建議        | 是    | 否    |
| 報告資料輸出        | 是    | 否    |
| 人類可讀摘要        | 可選   | 是    |
| 例外原因說明        | 可選   | 是    |

---

## 4. 技能依賴

以下依賴必須寫入技能定義中。技能執行前，腳本應先檢查依賴是否存在。若缺少依賴，技能不得執行。

### 4.1 系統依賴

```yaml
system_dependencies:
  - bash
  - git
  - curl
  - jq
  - python3
```

### 4.2 Python 依賴

```yaml
python_dependencies:
  - requests>=2.31
  - python-dateutil>=2.9
  - packaging>=24.0
  - pyyaml>=6.0
  - spdx-tools>=0.8
```

### 4.3 可選 CLI 依賴

```yaml
optional_cli_dependencies:
  - gh
  - npm
  - pip
  - go
```

### 4.4 權限依賴

```yaml
permissions:
  - network_access_to_api_github_com
  - read_public_repository_metadata
  - read_public_repository_files
  - local_cache_write
```

### 4.5 環境變數

```yaml
env_dependencies:
  GITHUB_TOKEN:
    required: true
    description: 用於存取 GitHub API，降低 rate limit 影響
  SKILL_CACHE_DIR:
    required: false
    default: .cache/github_prior_art_search
  SKILL_OUTPUT_DIR:
    required: false
    default: output/github_prior_art_search
```

---

## 5. 硬性規則

以下規則由腳本強制執行，模型不得覆寫。

```yaml
hard_rules:
  ignore_stars_below_100:
    enabled: true
    field: stargazers_count
    threshold: 100
    action: discard

  ignore_archived:
    enabled: true
    field: archived
    value: true
    action: discard

  ignore_disabled:
    enabled: true
    field: disabled
    value: true
    action: discard

  ignore_no_license_for_direct_reuse:
    enabled: true
    condition: license.spdx_id == null
    action: downgrade_to_reference_only
    risk_level: high

  manual_review_for_copyleft:
    enabled: true
    licenses:
      - GPL-3.0
      - AGPL-3.0
      - LGPL-3.0
      - MPL-2.0
      - SSPL-1.0
    action: require_manual_review

  max_deep_analysis_candidates:
    default: 8

  model_cannot_override_script_decision:
    enabled: true
```

---

## 6. 輸入格式

```yaml
project_goal:
  type: string
  required: true

core_features:
  type: array
  required: true

tech_stack:
  type: array
  required: false

domain:
  type: string
  required: false

architecture_style:
  type: array
  required: false

license_preference:
  type: array
  required: false
  default:
    - MIT
    - Apache-2.0
    - BSD-3-Clause

exclude_repos:
  type: array
  required: false

max_candidates:
  type: integer
  required: false
  default: 8

min_stars:
  type: integer
  required: false
  default: 100
  minimum: 100

last_commit_within_days:
  type: integer
  required: false
  default: 730
```

注意：即使輸入中 `min_stars` 被設為低於 100，腳本仍必須強制使用 100。

```text
effective_min_stars = max(input.min_stars, 100)
```

---

## 7. 技能輸出格式

技能必須輸出以下內容：

```yaml
outputs:
  - result.json
  - result.md
  - candidates.json
  - dependencies.json
  - decision.json
```

### 7.1 `result.json` 主要欄位

```json
{
  "skill": "github_prior_art_search",
  "status": "completed",
  "execution": {
    "started_at": "2026-08-23T00:00:00Z",
    "finished_at": "2026-08-23T00:05:00Z",
    "script_version": "1.1.0"
  },
  "project": {
    "goal": "string",
    "core_features": ["string"],
    "tech_stack": ["string"]
  },
  "search": {
    "queries": ["string"],
    "effective_min_stars": 100,
    "filters": {
      "archived": false,
      "disabled": false,
      "last_commit_within_days": 730
    }
  },
  "candidates": [
    {
      "repository": "owner/repo",
      "url": "https://github.com/owner/repo",
      "description": "string",
      "stars": 1200,
      "forks": 100,
      "language": "TypeScript",
      "license": "MIT",
      "pushed_at": "2026-07-01T00:00:00Z",
      "archived": false,
      "scores": {
        "relevance": 80,
        "reusability": 70,
        "maintenance_activity": 90,
        "code_quality": 60,
        "documentation": 70,
        "license_fit": 100,
        "total": 78
      },
      "reuse_decision": "use_as_template",
      "dependencies": {
        "manifests_found": ["package.json"],
        "runtime_count": 35,
        "dev_count": 42,
        "total_count": 77,
        "unpinned_count": 12,
        "known_risk_count": 0,
        "details": []
      },
      "risks": [
        {
          "type": "dependency_risk",
          "level": "medium",
          "detail": "存在多個未固定版本依賴。"
        }
      ],
      "summary": "由腳本產生的結構化摘要。"
    }
  ],
  "recommendation": {
    "primary_action": "use_as_template",
    "primary_repository": "owner/repo",
    "reason": "由腳本根據評分與規則產生。",
    "build_in_house_parts": ["string"],
    "next_steps": ["string"]
  },
  "warnings": []
}
```

---

## 8. 腳本執行流程

```text
1. 檢查技能依賴
2. 讀取輸入
3. 校验輸入
4. 產生搜尋查詢
5. 呼叫 GitHub API
6. 過濾星數低於 100 的專案
7. 過濾 archived、disabled
8. 過濾黑名單
9. 去重
10. 取得候選專案元資料
11. 解析授權
12. 解析依賴
13. 計算評分
14. 排序
15. 產生腳本決策
16. 輸出 JSON 與 Markdown
17. 可選：呼叫模型產生摘要
```

---

## 9. 關鍵字生成策略

為避免完全依賴模型，關鍵字生成應使用模板化腳本。

### 9.1 輸入欄位映射

```yaml
keyword_sources:
  project_goal:
    weight: 5
  core_features:
    weight: 4
  domain:
    weight: 3
  architecture_style:
    weight: 2
  tech_stack:
    weight: 2
```

### 9.2 模板化查詢

```text
{domain} admin dashboard stars:>=100
{feature} management system stars:>=100
{feature} engine stars:>=100
{tech_stack} {domain} stars:>=100
topic:{domain} stars:>=100
```

### 9.3 範例

輸入：

```yaml
project_goal: 遊戲活動配置後台
core_features:
  - 活動配置
  - 任務配置
  - 獎勵發放
  - 審核流程
domain: game_ops
tech_stack:
  - TypeScript
  - Node.js
```

腳本生成查詢：

```text
game ops admin dashboard stars:>=100
activity configuration management system stars:>=100
task configuration system stars:>=100
reward engine stars:>=100
approval workflow admin stars:>=100
language:TypeScript game admin stars:>=100
```

---

## 10. GitHub 搜尋腳本規則

### 10.1 使用 GitHub Search API

建議使用 GitHub REST API：

```text
GET https://api.github.com/search/repositories
```

必要查詢參數：

```text
q={query}+stars:>=100
sort=updated
order=desc
per_page=50
```

### 10.2 本地二次過濾

即使 API 已使用 `stars:>=100`，腳本仍必須再次過濾：

```python
if repo["stargazers_count"] < 100:
    continue
```

### 10.3 過濾條件

```python
if repo["archived"]:
    continue

if repo.get("disabled", False):
    continue

if repo["full_name"] in exclude_repos:
    continue

if repo["html_url"] in exclude_repos:
    continue
```

---

## 11. 授權解析腳本

授權判斷不得交給模型。

### 11.1 授權來源

優先使用 GitHub API 回傳的 license：

```json
{
  "license": {
    "spdx_id": "MIT"
  }
}
```

若 API 未回傳，腳本應下載倉庫根目錄檔案：

```text
LICENSE
LICENSE.txt
LICENSE.md
COPYING
COPYING.txt
```

### 11.2 授權分類

```yaml
license_policy:
  preferred:
    - MIT
    - Apache-2.0
    - BSD-2-Clause
    - BSD-3-Clause
  review_required:
    - MPL-2.0
    - LGPL-3.0
    - GPL-3.0
  high_risk:
    - AGPL-3.0
    - SSPL-1.0
  unknown:
    - NOASSERTION
    - null
```

### 11.3 腳本動作

```yaml
preferred:
  license_fit_score: 100

review_required:
  license_fit_score: 40
  action: require_manual_review

high_risk:
  license_fit_score: 10
  action: avoid_direct_reuse

unknown:
  license_fit_score: 0
  action: reference_only
  risk_level: high
```

---

## 12. 依賴解析腳本

被調研專案的依賴必須寫入輸出中。此步驟由腳本執行，不由模型推測。

### 12.1 支援的依賴清單

```yaml
dependency_manifests:
  npm:
    files:
      - package.json
    lockfiles:
      - package-lock.json
      - yarn.lock
      - pnpm-lock.yaml

  python:
    files:
      - requirements.txt
      - pyproject.toml
      - setup.py
      - poetry.lock
      - Pipfile.lock

  go:
    files:
      - go.mod

  rust:
    files:
      - Cargo.toml

  java:
    files:
      - pom.xml
      - build.gradle
      - build.gradle.kts
```

### 12.2 輸出欄位

```json
{
  "dependencies": {
    "manifests_found": ["package.json"],
    "runtime_count": 35,
    "dev_count": 42,
    "total_count": 77,
    "unpinned_count": 12,
    "known_risk_count": 0,
    "lockfile_present": true,
    "details": [
      {
        "ecosystem": "npm",
        "name": "react",
        "version": "^18.2.0",
        "type": "runtime",
        "pinned": false
      }
    ]
  }
}
```

### 12.3 風險標記規則

```yaml
dependency_risk_rules:
  high_total_dependencies:
    threshold: 200
    level: medium

  high_unpinned_dependencies:
    threshold: 20
    level: medium

  no_lockfile:
    level: medium

  outdated_major_versions:
    enabled: false
    reason: 需要生態系工具，預設不啟用

  known_vulnerabilities:
    enabled: false
    optional_tool: npm audit / pip-audit / govulncheck
```

---

## 13. 腳本評分模型

評分完全由腳本計算。

### 13.1 權重

```yaml
scoring_weights:
  relevance: 35
  reusability: 20
  maintenance_activity: 15
  code_quality: 10
  documentation: 10
  license_fit: 10
```

### 13.2 相關度

由腳本根據關鍵字命中計算。

```yaml
relevance_signals:
  name_match:
    weight: 20
  description_match:
    weight: 15
  topics_match:
    weight: 10
  readme_match:
    weight: 10
  feature_match:
    weight: 30
  tech_stack_match:
    weight: 15
```

若不希望下載 README，可關閉 `readme_match`，改使用 GitHub API 的 `description`、`topics`、`name`。

### 13.3 維護活躍度

```python
def maintenance_score(pushed_at, now):
    days = (now - pushed_at).days

    if days <= 90:
        return 100
    if days <= 180:
        return 85
    if days <= 365:
        return 70
    if days <= 730:
        return 40
    return 10
```

### 13.4 文件品質

```yaml
documentation_signals:
  has_readme:
    weight: 30
  readme_has_install:
    weight: 20
  readme_has_usage:
    weight: 20
  has_docs_folder:
    weight: 15
  has_examples_folder:
    weight: 15
```

### 13.5 程式碼品質訊號

```yaml
code_quality_signals:
  has_tests:
    weight: 25
  has_ci:
    weight: 25
  has_lint_config:
    weight: 15
  has_release:
    weight: 15
  has_src_structure:
    weight: 20
```

---

## 14. 腳本決策規則

最終採用建議由腳本根據規則產生。

```yaml
decision_rules:
  adopt_as_dependency:
    conditions:
      total_score: ">= 80"
      relevance: ">= 80"
      license_fit: ">= 90"
      maintenance_activity: ">= 70"
      dependency_risk: "<= medium"
      archived: false

  fork_and_modify:
    conditions:
      total_score: ">= 75"
      relevance: ">= 75"
      license_fit: ">= 70"
      maintenance_activity: ">= 50"

  use_as_template:
    conditions:
      total_score: ">= 70"
      relevance: ">= 70"
      license_fit: ">= 70"

  reference_architecture_only:
    conditions:
      total_score: ">= 55"
      relevance: ">= 60"

  avoid_due_to_risk:
    conditions:
      license_risk: high
      archived: true
      no_license: true
      security_risk: high

  build_in_house:
    conditions:
      no_candidate_meets_threshold: true
```

---

## 15. 模型使用限制

模型只能處理以下工作：

```yaml
model_allowed_tasks:
  - summarize_project_goal
  - extract_additional_keywords_from_user_text
  - generate_human_readable_summary
  - explain_why_no_candidates_found
```

模型不得處理：

```yaml
model_forbidden_tasks:
  - decide_whether_repository_is_valid
  - override_license_risk
  - override_star_threshold
  - change_reuse_decision
  - infer_dependencies_without_manifest
  - infer_license_without_file_or_api_field
  - create_candidates_not_returned_by_script
```

---

## 16. 技能定義檔範例

```yaml
name: github_prior_art_search
version: 1.1.0
execution_mode: script_first

entrypoint:
  command: python3 main.py
  args:
    - --input
    - "{{input_file}}"
    - --output-dir
    - "{{output_dir}}"

dependencies:
  system:
    - bash
    - git
    - curl
    - jq
    - python3
  python:
    - requests>=2.31
    - python-dateutil>=2.9
    - packaging>=24.0
    - pyyaml>=6.0
    - spdx-tools>=0.8
  optional_cli:
    - gh
    - npm
    - pip
    - go

env:
  GITHUB_TOKEN:
    required: true
  SKILL_CACHE_DIR:
    required: false
    default: .cache/github_prior_art_search
  SKILL_OUTPUT_DIR:
    required: false
    default: output/github_prior_art_search

inputs:
  project_goal:
    type: string
    required: true
  core_features:
    type: array
    required: true
  tech_stack:
    type: array
    required: false
  domain:
    type: string
    required: false
  architecture_style:
    type: array
    required: false
  license_preference:
    type: array
    required: false
  exclude_repos:
    type: array
    required: false
  max_candidates:
    type: integer
    required: false
    default: 8
  min_stars:
    type: integer
    required: false
    default: 100
    enforced_minimum: 100
  last_commit_within_days:
    type: integer
    required: false
    default: 730

hard_rules:
  ignore_stars_below_100: true
  ignore_archived: true
  ignore_disabled: true
  no_license_reference_only: true
  copyleft_manual_review: true
  model_cannot_override_script_decision: true

outputs:
  - result.json
  - result.md
  - candidates.json
  - dependencies.json
  - decision.json
```

---

## 17. 腳本偽代碼

```python
def main(input_path, output_dir):
    check_skill_dependencies()

    input_data = load_input(input_path)
    validate_input(input_data)

    min_stars = max(input_data.get("min_stars", 100), 100)

    queries = build_queries_from_template(input_data)

    raw_repos = []
    for query in queries:
        query = ensure_star_filter(query, min_stars)
        result = search_github_repositories(query)
        raw_repos.extend(result["items"])

    candidates = []

    for repo in raw_repos:
        if repo["stargazers_count"] < 100:
            continue

        if repo["archived"]:
            continue

        if repo.get("disabled", False):
            continue

        if repo["full_name"] in input_data.get("exclude_repos", []):
            continue

        candidates.append(repo)

    candidates = deduplicate(candidates)
    candidates = sort_initial(candidates)

    shortlist = candidates[:input_data.get("max_candidates", 8)]

    analyzed = []

    for repo in shortlist:
        metadata = fetch_repository_metadata(repo["full_name"])
        license_info = parse_license(metadata)
        files = fetch_file_tree(repo["full_name"])
        dependencies = parse_dependencies(repo["full_name"], files)
        documentation = parse_documentation(repo["full_name"], files)
        quality_signals = parse_quality_signals(files)

        scores = calculate_scores(
            input_data=input_data,
            metadata=metadata,
            license_info=license_info,
            dependencies=dependencies,
            documentation=documentation,
            quality_signals=quality_signals
        )

        risks = calculate_risks(
            license_info=license_info,
            dependencies=dependencies,
            metadata=metadata
        )

        decision = decide_reuse_strategy(scores, risks)

        analyzed.append({
            "repository": metadata["full_name"],
            "metadata": metadata,
            "license": license_info,
            "dependencies": dependencies,
            "documentation": documentation,
            "scores": scores,
            "risks": risks,
            "reuse_decision": decision
        })

    recommendation = build_recommendation(analyzed)

    write_outputs(
        output_dir=output_dir,
        input_data=input_data,
        queries=queries,
        candidates=analyzed,
        recommendation=recommendation
    )
```

---

## 18. 關鍵 Bash 腳本範例

以下為可直接作為技能腳本雛形的片段。

```bash
#!/usr/bin/env bash
set -euo pipefail

MIN_STARS=100
QUERY="$1"
TOKEN="${GITHUB_TOKEN}"

SEARCH_QUERY="${QUERY} stars:>=${MIN_STARS}"

curl -s \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://api.github.com/search/repositories?q=${SEARCH_QUERY}&per_page=50" \
  | jq '.items[]
    | select(.stargazers_count >= 100)
    | select(.archived == false)
    | select(.disabled == false)
    | {
        full_name,
        html_url,
        description,
        stargazers_count,
        forks_count,
        language,
        license: .license.spdx_id,
        pushed_at,
        archived
      }'
```

---

## 19. 依賴解析腳本範例

```python
import json
from pathlib import Path


def parse_package_json(path: Path):
    data = json.loads(path.read_text())

    runtime_dependencies = data.get("dependencies", {})
    dev_dependencies = data.get("devDependencies", {})

    dependencies = []

    for name, version in runtime_dependencies.items():
        dependencies.append({
            "ecosystem": "npm",
            "name": name,
            "version": version,
            "type": "runtime",
            "pinned": is_pinned_version(version)
        })

    for name, version in dev_dependencies.items():
        dependencies.append({
            "ecosystem": "npm",
            "name": name,
            "version": version,
            "type": "dev",
            "pinned": is_pinned_version(version)
        })

    return dependencies


def is_pinned_version(version: str) -> bool:
    if not version:
        return False

    if version.startswith("^"):
        return False

    if version.startswith("~"):
        return False

    if version in ("latest", "next", "*"):
        return False

    return True
```

---

## 20. Markdown 報告生成規則

Markdown 報告也应由腳本模板產生，不由模型自由撰寫。

```markdown
# GitHub 先行調研報告

## 專案輸入
- 專案目標：{{project_goal}}
- 核心功能：{{core_features}}
- 技術堆疊：{{tech_stack}}

## 搜尋條件
- 最低星數：100
- 忽略封存專案：是
- 忽略禁用專案：是
- 最後提交限制：{{last_commit_within_days}} 天

## 候選專案
| 專案 | 星數 | 授權 | 最後更新 | 總分 | 決策 |
|---|---:|---|---|---:|---|
{% for candidate in candidates %}
| {{ candidate.repository }} | {{ candidate.metadata.stargazers_count }} | {{ candidate.license.spdx_id }} | {{ candidate.metadata.pushed_at }} | {{ candidate.scores.total }} | {{ candidate.reuse_decision }} |
{% endfor %}

## 建議
- 主要動作：{{recommendation.primary_action}}
- 主要原因：{{recommendation.reason}}
- 需自行開發部分：{{recommendation.build_in_house_parts}}
```

---

## 21. 模型摘要使用方式

若仍需要模型摘要，應使用受限模板，且不允許模型修改結構化欄位。

### 21.1 模型輸入

```json
{
  "task": "generate_summary_only",
  "result_json": "..."
}
```

### 21.2 模型輸出限制

```yaml
model_output_schema:
  type: object
  additionalProperties: false
  properties:
    executive_summary:
      type: string
      maxLength: 500
    notable_observations:
      type: array
      items:
        type: string
      maxItems: 5
```

### 21.3 禁止事項

```text
不得更改候選專案排序。
不得更改評分。
不得更改授權風險等級。
不得新增候選專案。
不得推翻腳本決策。
不得推測依賴。
不得推測授權。
```

---

## 22. 技能驗收標準

### 22.1 功能驗收

```yaml
acceptance_criteria:
  - 星數低於 100 的專案不會出現在最終候選清單中
  - archived 專案不會進入深度分析
  - 無授權專案必須被標記為 high_risk
  - 依賴清單必須寫入 dependencies.json
  - 所有最終決策必須來自腳本規則
  - 模型摘要不得覆寫腳本決策
  - 缺少 GITHUB_TOKEN 時技能必須失敗並回報原因
  - 缺少依賴時技能必須失敗並回報缺少的依賴
```

### 22.2 輸出驗收

```yaml
output_validation:
  - result.json 必須包含 candidates
  - candidates 中每個專案必須包含 dependencies
  - candidates 中每個專案必須包含 license
  - candidates 中每個專案必須包含 scores
  - decision.json 必須包含主要推薦動作
  - result.md 必須可由腳本模板重現
```

### 22.3 異常驗收

```yaml
exception_validation:
  - GitHub API rate limit 時必須標記 status=partial
  - 無法取得依賴清單時必須標記 dependency_parsing_failed
  - 無法取得授權時必須標記 license=unknown
  - 無候選專案時必須輸出 build_in_house 建議
```

---

## 23. 最終建議技能結構

```text
github_prior_art_search/
  main.py
  config.yaml
  templates/
    queries.yaml
    report.md.jinja2
  scripts/
    check_dependencies.sh
    search_github.py
    parse_license.py
    parse_dependencies.py
    score_candidates.py
    build_recommendation.py
  tests/
    test_star_filter.py
    test_license_rules.py
    test_dependency_parser.py
    test_decision_rules.py
  output/
  cache/
```

---

## 24. 結論

此版本技能應定位為「可執行腳本」而非「模型自由推理任務」。

關鍵設計如下：

1. `stars < 100` 由腳本直接忽略。  
2. `archived`、`disabled` 由腳本直接忽略。  
3. 授權、依賴、評分、決策全部由腳本計算。  
4. 技能自身依賴與目標專案依賴都必須寫入技能與輸出。  
5. 模型僅允許生成摘要，不允許改變任何決策。  
6. 報告以結構化 JSON 為主，Markdown 為腳本模板產出。  

這樣的設計較適合納入正式 Agent 工作流程，也較容易進行審計、測試與重現。
