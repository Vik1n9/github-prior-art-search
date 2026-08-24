import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


@pytest.fixture(scope="session")
def config():
    from scripts.common import load_config
    return load_config()


def repo(full_name="owner/repo", stars=500, archived=False, disabled=False,
         pushed_at="2026-08-01T00:00:00Z", html_url=None, **extra):
    return {
        "full_name": full_name,
        "html_url": html_url or f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "archived": archived,
        "disabled": disabled,
        "pushed_at": pushed_at,
        "description": "",
        "topics": [],
        "language": None,
        **extra,
    }
