# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

A prior-art search and reuse-check Agent Skill for GitHub, following the
[Agent Skills](https://agentskills.io) standard (`SKILL.md`). Requires Python
3.9+ standard library only.

## How it works

| Stage | Owner | Output |
|---|---|---|
| 1. Split the requirement into functional components | Model | `components` in `input.json` |
| 2. Design match terms and search queries per component | Model | `match_terms`, `search_queries` |
| 3. Search, hard-filter, collect facts, set a reuse cap per repo | Script (`search`) | `result.json`, `result.md` |
| 4. Judge each candidate against the original requirement | Model | `assessment.json` |
| 5. Validate the judgment and write the final report | Script (`finalize`) | `final.json`, `final.md` |

The script enforces the hard rules: stars ≥ 100, no archived/disabled repos,
and a per-repository `cap` derived from license, maintenance activity and
dependency risk. `finalize` rejects any assessment that picks a repository
outside a component's candidates, exceeds its cap, or does not account for
every `must_have` item.

## Install

As an OpenCode command:

```bash
cp command/github-search.md ~/.config/opencode/command/
```

The skill itself must be installed at
`~/.config/opencode/skills/github-prior-art-search/`. Then invoke with
`/github-search <requirement>`.

## Run

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py search --input input.example.json --dry-run
python3 main.py search --input input.example.json --output-dir out
python3 main.py search --input input.example.json --output-dir out --only redis-store
python3 main.py finalize --assessment assessment.json --output-dir out
```

See `input.example.json` and `assessment.example.json` for the formats, and
`SKILL.md` for the full field rules.

## Test

```bash
python3 -m pytest tests/ -v
```

Tests run offline against a fake GitHub.

## License

[MIT](LICENSE)
