"""Is there a newer version of Wony?

Checks only — it never pulls. Updating changes dependencies as well as code, so
the safe end of that is a person running the two commands with the output in
front of them.
"""
import subprocess
import typing

from helpers.paths import REPO_ROOT

_TIMEOUT_SECONDS = 25


def _git(*args: str) -> typing.Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def check() -> str:
    """One sentence about whether an update is waiting, fit to show a user."""
    if _git("rev-parse", "--git-dir") is None:
        return (
            "Can't check for updates — this copy of Wony isn't a git checkout, "
            "so there's nothing to compare against."
        )

    if _git("fetch", "--quiet") is None:
        return "Couldn't reach the update server. Check your internet connection."

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    counts = _git("rev-list", "--left-right", "--count", f"{branch}...origin/{branch}")
    if not counts:
        return f"No update information for the '{branch}' branch."

    try:
        ahead, behind = (int(part) for part in counts.split())
    except ValueError:
        return "Couldn't read the update information."

    if behind == 0:
        return "Wony is up to date."

    change = "change" if behind == 1 else "changes"
    warning = " You have local edits that a update would need merging with." if ahead else ""
    return (
        f"{behind} new {change} available.{warning} To update, run:\n"
        "    git pull\n"
        "    python setup.py"
    )
