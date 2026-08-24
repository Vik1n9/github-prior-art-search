---
name: github-prior-art-search
description: >-
  GitHub 先行調研與重用檢查：在動手開發前，搜尋並評估 GitHub 上是否已有可採用、
  可 fork 或可參考的既有專案。以 script-first 模式執行：星數過濾（強制 ≥100）、
  archived/disabled 過濾、授權風險標記、依賴解析、六維度加權評分與重用決策全部由
  腳本計算，模型僅能依受限 schema 產生文字摘要，不得更改任何決策。
  當使用者提到「先行調研」「prior art」「有沒有現成的專案」「不要重造輪子」
  「找類似的開源方案」「評估能不能直接用某 repo」時，務必使用此技能。
compatibility: >-
  Requires Python 3.9+ (standard library only, no pip packages),
  network access to api.github.com, and the GITHUB_TOKEN environment variable.
license: MIT
metadata:
  version: "1.3.0"
  execution_mode: script_first
---

# GitHub Prior Art Search（Script-First）

## 核心原則

1. **所有硬性條件由腳本判斷**——星數 <100 直接忽略；archived/disabled 直接忽略；
   授權風險由腳本標記；依賴清單由腳本解析寫入輸出。
2. **模型不得產生最終採用結論**——你只能針對腳本結果產生文字摘要。
3. 所有腳本輸出必須可重現；腳本無法取得資料時會明確標記 `partial` 或 `failed`。

## 執行流程

### 步驟 1：準備輸入 JSON

向使用者收集必要欄位後寫入暫存檔（以下僅為格式示範，欄位值一律取自使用者的實際專案）：

```json
{
  "project_goal": "API 速率限制中介層",
  "core_features": ["滑動視窗限流", "多租戶配額", "Redis 儲存"],
  "tech_stack": ["Go", "Redis"],
  "domain": "rate_limiting",
  "architecture_style": [],
  "exclude_repos": [],
  "max_candidates": 8,
  "min_stars": 100,
  "last_commit_within_days": 730,
  "extra_keywords": [
    "rate limiter middleware",
    "sliding window rate limit",
    "topic:rate-limiting"
  ]
}
```

- 必填：`project_goal`、`core_features`
- `min_stars` 即使設低於 100，腳本仍強制使用 100
- **`extra_keywords` 是搜尋查詢的唯一來源，請務必填寫。** 把使用者的描述轉成
  3–8 條**英文**技術關鍵字：GitHub 語料以英文為主，非英文查詢命中率極低，而
  只有你能把「滑動視窗限流」翻成 `sliding window rate limit`。可善用 GitHub
  搜尋語法（如 `topic:rate-limiting`，注意 topic 是連字號 slug、不接受空白）。
  這是你唯一允許參與的搜尋環節——腳本不會替你臆造查詢。
- 未提供 `extra_keywords` 時，腳本只會以 `project_goal` 原文查詢一次，並記入
  `no_extra_keywords` 警告、將 `status` 標為 `partial`。

### 步驟 2：執行腳本

```bash
python3 main.py --input /tmp/prior_art_input.json --output-dir output/github-prior-art-search
```

腳本會自行驗證 Python 版本與 `GITHUB_TOKEN`；任一缺失時以非零結束並印出原因，
**不得繞過**。缺少 `GITHUB_TOKEN` 時請使用者自行設定，不得猜測或代填。

### 步驟 3：讀取結構化結果並產生受限摘要

讀取 `output/github-prior-art-search/result.json`，然後**僅**產生以下 schema 的
摘要內容（附加於報告末尾的「模型摘要」區塊）：

```json
{
  "executive_summary": "≤500 字",
  "notable_observations": ["最多 5 條"]
}
```

## 模型禁止事項（硬性規則）

- 不得決定倉庫是否有效、不得覆寫星數門檻
- 不得覆寫或推翻授權風險等級與重用決策
- 不得新增/刪除候選專案、不得更改排序與評分
- 不得在無 manifest 時推測依賴、無授權欄位或檔案時推測授權
- 不得修改 `result.json` 的任何結構化欄位

## 輸出檔案

| 檔案 | 內容 |
|---|---|
| `result.json` | 完整結果（狀態、查詢、候選、依賴、評分、建議、警告） |
| `result.md` | 人類可讀報告 |

## 異常處理

- `status=partial`：部分查詢或解析失敗，詳見 `warnings`，照實告知使用者。
- 無候選 → 建議 `build_in_house`。
- 缺少 `GITHUB_TOKEN` 或 Python 版本過低 → 腳本以非零結束並回報原因。

詳細規則（評分訊號、決策優先序、reusability 定義）見 [references/RULES.md](references/RULES.md)。
