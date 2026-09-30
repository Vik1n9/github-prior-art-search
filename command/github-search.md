---
description: GitHub 先行調研：把需求拆成功能組件，逐組件搜尋可採用／fork／參考的既有專案並判斷適配（星數≥100、授權與依賴上限由腳本判定）
agent: build
---

請使用 `github-prior-art-search` 技能執行先行調研。使用者需求如下：

```
$ARGUMENTS
```

依技能的 `SKILL.md` 流程執行：由你拆解功能組件、設計 `match_terms` 與
`search_queries`，執行 search，逐組件判斷適配後撰寫 assessment 並 finalize。

若使用者需求不足以拆出具體的功能組件與 `must_have`，先提問補齊，不得自行虛構。
