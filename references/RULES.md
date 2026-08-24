# 評分與決策規則詳解

本文件補充 `config.json` 中各規則的計算細節與設計決定。所有規則由腳本執行，
模型不得覆寫。

## 1. 評分模型

六個子分數皆為 0–100，加權總分 = Σ(子分數 × 權重) / 100：

| 子分數 | 權重 | 來源 |
|---|---:|---|
| relevance | 35 | 六訊號加權（見 1.1） |
| reusability | 20 | 檔案樹與依賴摘要推導（見 1.2） |
| maintenance_activity | 15 | 最後提交時間分桶（見 1.3） |
| code_quality | 10 | 五訊號（見 1.4） |
| documentation | 10 | 五訊號（見 1.4） |
| license_fit | 10 | 授權分類分數（見 2） |

### 1.1 相關度訊號

| 訊號 | 權重 | 計算方式 |
|---|---:|---|
| name_match | 20 | 目標+領域詞命中 repo 名稱的比例 |
| description_match | 15 | 目標+功能詞命中描述的比例 |
| topics_match | 10 | 領域+架構詞命中 topics 的比例 |
| readme_match | 10 | 目標+功能詞命中 README 的比例（可於 config 停用） |
| feature_match | 30 | 核心功能被 名稱/描述/topics/README 任一覆蓋的比例 |
| tech_stack_match | 15 | 技術棧命中 language/topics/描述 的比例 |

比對規則：英文詞以詞邊界正則比對；CJK 詞以子字串比對（`common.term_matches`）。

### 1.2 reusability（滿分 20）

可從檔案樹與依賴摘要推導的訊號：

| 訊號 | 分值 | 說明 |
|---|---:|---|
| lockfile_present | 5 | 版本可重現性 |
| has_release_or_tags | 4 | 有正式 release |
| moderate_dependency_count | 4 | 總依賴 ≤100 滿分、≥200 零分、線性內插 |
| has_examples | 4 | 頂層有 examples/samples |
| packaged_project | 3 | 有 Dockerfile 或任一套件清單 |

### 1.3 維護活躍度

≤90 天=100；≤180=85；≤365=70；≤730=40；>730=10；無資料=0。

### 1.4 文件與程式碼品質

- 文件（滿分 100 內）：has_readme 30／readme_has_install 20／readme_has_usage 20／
  has_docs_folder 15／has_examples_folder 15。
- 品質：has_tests 25／has_ci 25／has_lint_config 15／has_release 15／
  has_src_structure 20。測試偵測涵蓋 test/tests/spec/__tests__ 目錄與
  test_*.* / *_test.py / *.test.js / *.spec.js 檔名。

## 2. 授權政策

| 分類 | 授權 | fit_score | 動作 | 風險 |
|---|---|---:|---|---|
| preferred | MIT、Apache-2.0、BSD-2/3-Clause | 100 | allow_reuse | low |
| review_required | MPL-2.0、LGPL-3.0、GPL-3.0 | 40 | require_manual_review | medium |
| high_risk | AGPL-3.0、SSPL-1.0 | 10 | avoid_direct_reuse | high |
| unknown | 無授權 / NOASSERTION / 未識別 | 0 | reference_only | high |

- 授權來源僅限 API `license.spdx_id`；API 未回傳時標記 `license_file_unparsed`
  且仍歸 unknown——**腳本不解析授權檔內容，模型不得推測**。
- 政策清單外的有效 SPDX ID 保守歸入 review_required。

## 3. 依賴風險規則

- 總依賴 >200 → medium
- 未固定版本 >20 → medium（`^ ~ * latest next >= < x-range` 皆視為未固定）
- 有依賴但無 lockfile → medium
- 過期主版本與已知漏洞需要生態系專用工具（npm audit／pip-audit／govulncheck），
  不在本技能範圍內。

## 4. 決策優先序

多條件同時成立時採「先排除風險，再由嚴格到寬鬆」：

```
avoid_due_to_risk > adopt_as_dependency > fork_and_modify
                  > use_as_template > reference_architecture_only
```

| 規則 | total | relevance | 其他門檻 |
|---|--:|--:|---|
| adopt_as_dependency | ≥80 | ≥80 | license_fit≥90、maintenance≥70、dep_risk≤medium |
| fork_and_modify | ≥75 | ≥75 | license_fit≥70、maintenance≥50 |
| use_as_template | ≥70 | ≥70 | license_fit≥70 |
| reference_architecture_only | ≥55 | ≥60 | — |

- 任一候選命中即停止評估（取最高優先序）。
- 全部不符 → 該候選 `insufficient_fit`；整體建議改為 `build_in_house`，
  並附帶無候選警告。
- `avoid_due_to_risk` 觸發條件：license_risk=high 或 archived=true。

## 5. 執行狀態語意

| status | 觸發條件 |
|---|---|
| completed | 全部查詢與分析成功 |
| partial | 任一查詢 rate limit／失敗、檔案樹抓取失敗、release 查詢失敗、依賴解析失敗 |
| failed（exit 1） | 缺 GITHUB_TOKEN、Python 版本過低、輸入不合法等致命錯誤 |

檔案樹被截斷會記入 warnings（`tree_truncated`）但不改變 status。

## 6. Rate Limit 對策

Search API 認證後上限 30 req/min，單次執行查詢數上限 10，遠低於上限，因此不做
固定節流。遇到 403/429 且 `x-ratelimit-remaining` 為 0 時，讀取
`x-ratelimit-reset` 等待後重試一次；仍失敗則回報 `rate_limit`，該次執行停止後續
查詢，並將警告記入 warnings 使最終 status=partial。

本技能不做磁碟快取：候選是否「最近仍在維護」是核心過濾條件，快取會讓重跑拿到
過期資料，而單輪執行的請求量本來就遠低於額度。
