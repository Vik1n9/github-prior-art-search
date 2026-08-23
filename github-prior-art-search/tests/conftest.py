# -*- coding: utf-8 -*-
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
for p in (str(SCRIPTS_DIR), str(SKILL_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def config():
    from common import load_config
    return load_config()


def repo(full_name="owner/repo", stars=500, archived=False, disabled=False,
         pushed_at="2026-08-01T00:00:00Z", html_url=None, **extra):
    data = {
        "full_name": full_name,
        "html_url": html_url or f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "archived": archived,
        "disabled": disabled,
        "pushed_at": pushed_at,
        "description": "",
        "topics": [],
        "language": None,
    }
    data.update(extra)
    return data
