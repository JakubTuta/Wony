"""Repo-root anchored paths.

Every data file Wony owns (db, cache, credentials, logs, models) must resolve
against the repo, not the process CWD — the tray is launched by Task Scheduler
and `wony.py text` can be run from anywhere, and both used to fork their own
copy of wony.db / cache.json wherever they happened to start.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_path(*parts: str) -> str:
    """Join `parts` under the repo root."""
    return os.path.join(REPO_ROOT, *parts)


def resolve(path: str) -> str:
    """Resolve a config-supplied path: absolute stays, relative anchors to repo."""
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
