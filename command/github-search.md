---
description: GitHub 先行調研：開發前搜尋可採用／fork／參考的既有專案（script-first，星數≥100、授權與依賴風險由腳本判定）
agent: build
---

請使用 `github-prior-art-search` 技能執行先行調研。使用者輸入如下：

```
$ARGUMENTS
```

技能根目錄：`~/.config/opencode/skills/github-prior-art-search`
（以下以 `$SKILL` 代表此路徑）

嚴格遵循 `SKILL.md` 流程執行：

1. **依賴檢查**：`bash $SKILL/scripts/check_dependencies.sh`；失敗即停止並回報原因。
2. **確認 GITHUB_TOKEN**：`[ -n "$GITHUB_TOKEN" ] && echo OK || echo MISSING`；
   缺失時停止並請使用者設定，不得猜測或代填。
3. **準備輸入 JSON**（§6）：從使用者輸入萃取欄位並寫入暫存檔：
   - 必填 `project_goal`、`core_features`——若輸入無法推得具體目標或功能，
     先向使用者提問補齊，不得自行虛構。
   - 選填盡量萃取：`tech_stack`、`domain`、`architecture_style`、
     `license_preference`、`exclude_repos`、`max_candidates`、`min_stars`。
   - 你可以（也建議）將關鍵概念轉為英文關鍵字填入 `extra_keywords` 提升命中率；
     這是你唯一允許參與的搜尋環節。
4. **執行腳本**：`python3 $SKILL/main.py --input <暫存檔> --output-dir output/github-prior-art-search`
5. **回報結果**：讀取 `output/github-prior-art-search/result.json`，向使用者報告：
   - 執行狀態（completed/partial）與警告數量
   - 主要建議（primary_action）與原因
   - 前 3 名候選：名稱、星數、授權、總分、決策、一句話說明
   - 附加受限摘要區塊：`executive_summary`（≤500 字）與
     `notable_observations`（最多 5 條）
6. 若 `status=partial` 或有 warnings，照實告知使用者。

**禁止事項**（SKILL.md 硬性規則）：不得覆寫星數門檻、評分、排序或重用決策；
不得新增/刪除候選專案；無資料時不得推測，照實回報 failed/partial。
