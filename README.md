# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

A prior-art search and reuse-check Agent Skill for GitHub, following the
[Agent Skills](https://agentskills.io) standard (`SKILL.md`). Requires Python
3.9+ standard library only.

## Install

As an OpenCode command:

```bash
cp command/github-search.md ~/.config/opencode/command/
```

The skill itself must be installed at
`~/.config/opencode/skills/github-prior-art-search/`. Then invoke with
`/github-search <project goal + features + tech stack>`.

## Run

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

## Input

| Field | Required | Role |
|---|---|---|
| `search_queries` | yes | Queries sent to GitHub, designed by the calling agent and run verbatim with the star filter appended |
| `project_goal`, `core_features` | yes | Scoring criteria |
| `tech_stack`, `domain`, `architecture_style` | no | Scoring criteria |
| `exclude_repos`, `max_candidates`, `last_commit_within_days` | no | Filters |
| `min_stars` | no | A value below 100 is forced back up to 100 |

## Output

| File | Content |
|---|---|
| `result.json` | Status, queries, candidates with scores/licenses/dependencies/risks, recommendation, warnings |
| `result.md` | Human-readable report |

Exit status is non-zero when required inputs are missing or the run fails;
partial failures set `status = "partial"` with details in `warnings`.

## Test

```bash
python3 -m pytest tests/ -v
```

## License

[MIT](LICENSE)
