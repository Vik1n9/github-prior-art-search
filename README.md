# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

A **prior-art search and reuse-check Agent Skill** for GitHub. Before you build
from scratch, it finds existing projects worth adopting as a dependency,
forking, or using as a reference — so you never reinvent the wheel.

It follows the [Agent Skills](https://agentskills.io) standard (`SKILL.md`) and
works with skill-capable coding agents such as OpenCode or Claude Code.

## Why "script-first"

LLM-driven research is unreliable for hard requirements. This skill moves every
decision into deterministic scripts; the model may only summarize results under
a restricted schema:

| Hard rule | Enforcement |
|---|---|
| Ignore repos with < 100 stars | Script filter, model cannot lower the floor |
| Ignore archived / disabled repos | Script filter |
| Repos with no license are never "adopt directly" | Downgraded to reference-only, high risk |
| Copyleft licenses require manual review | Script flag |
| Scoring & reuse decision | Six-dimension weighted score computed in code |
| Model output | Text summary only; cannot add/remove candidates, change ranking, or override decisions |

All rules live in data files (`config.json`, `templates/queries.json`) rather
than code, so behavior is auditable and reproducible.

**Zero third-party dependencies**: Python 3.9+ standard library and bash only —
no pip, no venv.

## Quick start

### As an OpenCode command (recommended)

Copy the command file to your global commands directory:

```bash
cp command/github-search.md ~/.config/opencode/command/
```

Then invoke from any project with `/github-search <project goal + features + tech stack>`,
e.g. `/github-search 遊戲活動配置後台，活動配置／獎勵發放，TypeScript Node.js`.

The skill itself must be installed globally as well
(`~/.config/opencode/skills/github-prior-art-search/`).

### Manual

```bash
# 1. Dependency check (refuses to run and prints what's missing)
bash scripts/check_dependencies.sh

# 2. Set a token
export GITHUB_TOKEN=ghp_xxx

# 3. Prepare an input JSON (see SKILL.md / input.example.json) and run
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

Input requires `project_goal` and `core_features`; optional fields include
`tech_stack`, `domain`, `license_preference`, `exclude_repos`, `extra_keywords`,
`max_candidates`, `min_stars` (a value below 100 is forced back up to 100).

Outputs are written to the output directory:

| File | Content |
|---|---|
| `result.json` | Full result (status, queries, candidates, recommendation, warnings) |
| `result.md` | Human-readable report |
| `candidates.json` | Candidate list with scores and risks |
| `dependencies.json` | Parsed dependencies per candidate |
| `decision.json` | Primary recommendation and per-candidate decisions |

Exit status is non-zero when required inputs are missing or the run fails;
partial failures set `status = "partial"` with details in `warnings`.

## How it works

1. Validate input and enforce hard rules (star floor ≥ 100).
2. Build search queries from templates (`templates/queries.json`), expanding
   goal/domain/features/tech-stack placeholders with Cartesian products.
3. Query the GitHub Search API (rate-limit aware, disk-cached).
4. Re-filter locally: stars, archived/disabled, blacklist, last commit age.
5. Deep-analyze top N candidates: file tree, README, license detection,
   dependency manifests/lockfiles, releases.
6. Score six dimensions (relevance, reusability, maintenance activity, code
   quality, documentation, license fit) and decide: adopt / fork /
   use-as-template / reference-only / build-in-house.

Details of scoring signals and decision thresholds are documented in
[references/RULES.md](references/RULES.md).

## Testing

```bash
python3 -m pytest tests/ -v   # pytest is a dev/test-only dependency
```

All tests run offline against mocked GitHub responses.

## Project layout

```
├── SKILL.md              # Agent Skills standard definition
├── main.py               # Entry point (execution flow + report rendering)
├── config.json           # Rules as data: hard rules / weights / license policy / decision gates
├── templates/
│   └── queries.json      # §9 query templates (single source of truth)
├── scripts/
│   ├── check_dependencies.sh   # Dependency check (bash + Python 3.9+ only)
│   ├── common.py               # Config, cached HTTP client (urllib), text matching
│   ├── search_github.py        # Input validation, query building, search & filtering
│   ├── parse_license.py        # License parsing and classification
│   ├── parse_dependencies.py   # Dependency manifest parsing
│   ├── score_candidates.py     # Scoring model
│   └── build_recommendation.py # Decision rules
├── tests/                # pytest (offline)
└── references/RULES.md   # Rule details and design decisions
```

## License

[MIT](LICENSE)
