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

Scoring weights, license policy, dependency-risk thresholds and decision gates
live in `config.json`, so they can be audited and tuned without touching code.
The star floor and the archived/disabled filters are enforced in
`scripts/search_github.py` itself — deliberately not configurable.

**Zero third-party dependencies**: Python 3.9+ standard library only — no pip,
no venv.

## Quick start

### As an OpenCode command (recommended)

Copy the command file to your global commands directory:

```bash
cp command/github-search.md ~/.config/opencode/command/
```

Then invoke from any project with `/github-search <project goal + features + tech stack>`,
e.g. `/github-search a Go API rate limiter with sliding-window and Redis storage`.

The skill itself must be installed globally as well
(`~/.config/opencode/skills/github-prior-art-search/`).

### Manual

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

The script validates the Python version and `GITHUB_TOKEN` itself and exits
non-zero with the reason if either is missing.

Input requires `project_goal` and `core_features`; optional fields include
`tech_stack`, `domain`, `architecture_style`, `exclude_repos`, `extra_keywords`,
`max_candidates`, `last_commit_within_days`, and `min_stars` (a value below 100
is forced back up to 100).

Two files are written to the output directory:

| File | Content |
|---|---|
| `result.json` | Full result: status, queries, candidates with scores/licenses/dependencies/risks, recommendation, warnings |
| `result.md` | Human-readable report |

Exit status is non-zero when required inputs are missing or the run fails;
partial failures set `status = "partial"` with details in `warnings`.

## How it works

1. Validate input and enforce hard rules (star floor ≥ 100).
2. Build search queries from templates (`templates/queries.json`), expanding
   goal/domain/features/tech-stack placeholders with Cartesian products.
3. Query the GitHub Search API (rate-limit aware, stops early once exhausted).
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
├── main.py               # Entry point and pipeline orchestration
├── config.json           # Weights, license policy, dependency risk, decision gates
├── templates/
│   └── queries.json      # Query templates
├── scripts/
│   ├── common.py               # Config, HTTP client (urllib), text matching
│   ├── search_github.py        # Input validation, query building, search & filtering
│   ├── analyze.py              # Per-candidate deep analysis
│   ├── parse_license.py        # License parsing and classification
│   ├── parse_dependencies.py   # Dependency manifest parsing
│   ├── score_candidates.py     # Scoring model
│   ├── build_recommendation.py # Decision rules
│   └── render_report.py        # result.json / result.md output
├── tests/                # pytest (offline)
└── references/RULES.md   # Rule details and design decisions
```

## License

[MIT](LICENSE)
