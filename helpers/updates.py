"""Is there a newer version of Wony, and putting it in place.

A git checkout updates with `git pull`; a copy downloaded as a ZIP updates from
GitHub's archive of the same branch. Either way `setup.py update` then brings
the packages and the web page up to the new code, and the tray restarts.

Stdlib only: setup.py imports this before anything is installed, to fetch the
web page it would otherwise need Node.js to build.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import typing
import urllib.request
import zipfile

from helpers.paths import REPO_ROOT, repo_path

_REPO = "JakubTuta/Wony"
_BRANCH = "main"
# Release whose assets are the built web page, one per version of web/ (CI:
# .github/workflows/web-ui.yml), plus the newest under a fixed name.
_WEB_RELEASE = f"https://github.com/{_REPO}/releases/download/web-ui"
_LATEST_WEB = "wony-web-latest.zip"

_GIT_TIMEOUT_SECONDS = 25
_HTTP_TIMEOUT_SECONDS = 60
_SETUP_TIMEOUT_SECONDS = 1800

# A ZIP install has no git history: these say which commit it is and which files
# came with it, so the next update can remove the ones that were deleted.
_VERSION_FILE = repo_path(".wony_version")
_MANIFEST_FILE = repo_path(".wony_files")

_available = False


def _git(*args: str) -> typing.Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_git_checkout() -> bool:
    return _git("rev-parse", "--git-dir") is not None


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Wony-updater"})
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def available() -> bool:
    """Whether the last check found an update that Update now can install."""
    return _available


def check() -> str:
    """One sentence about whether an update is waiting, fit to show a user."""
    global _available
    _available = False
    if not _is_git_checkout():
        return _check_zip()

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
    if ahead or _local_edits():
        return (
            f"{behind} new {change} available, but this copy has local edits, so it has "
            "to be updated by hand:\n    git pull\n    python setup.py update"
        )
    _available = True
    return f"{behind} new {change} available. Right-click the tray icon → Update now."


def _check_zip() -> str:
    global _available
    try:
        latest = json.loads(_download(f"https://api.github.com/repos/{_REPO}/commits/{_BRANCH}"))["sha"]
    except Exception:
        return "Couldn't reach the update server. Check your internet connection."
    if _read(_VERSION_FILE) == latest:
        return "Wony is up to date."
    _available = True
    return "A newer Wony is available. Right-click the tray icon → Update now."


def _local_edits() -> bool:
    return bool(_git("status", "--porcelain", "--untracked-files=no"))


def apply() -> typing.Tuple[bool, str]:
    """Put the newest code in place and run `setup.py update` for it. Returns
    (worked, what to tell the user); the caller restarts Wony when it worked."""
    try:
        if _is_git_checkout():
            if _local_edits():
                return False, "This copy has local edits. Update it by hand: git pull, then python setup.py update."
            if _git("pull", "--ff-only", "--quiet") is None:
                return False, "git pull failed. Open a terminal here and run: git pull"
        else:
            _apply_zip()
    except Exception as e:
        return False, f"The update didn't download: {e}"

    ok, log = _run_setup_update()
    if not ok:
        return False, f"The new code is in place, but finishing the install failed. Details: {log}"
    global _available
    _available = False
    return True, "Updated. Restarting…"


def _apply_zip() -> None:
    data = _download(f"https://github.com/{_REPO}/archive/refs/heads/{_BRANCH}.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # GitHub writes the commit id as the archive's comment.
        sha = archive.comment.decode("ascii", "ignore").strip()
        members = [info for info in archive.infolist() if not info.is_dir()]
        prefix = members[0].filename.split("/", 1)[0] + "/"
        files: typing.Dict[str, zipfile.ZipInfo] = {}
        for info in members:
            relative = info.filename[len(prefix):]
            if relative and not _escapes(relative):
                files[relative] = info
        for relative, info in files.items():
            target = os.path.join(REPO_ROOT, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)

    for relative in set(_read(_MANIFEST_FILE).splitlines()) - set(files):
        path = os.path.join(REPO_ROOT, *relative.split("/"))
        if relative and not _escapes(relative) and os.path.isfile(path):
            os.remove(path)
    _write(_MANIFEST_FILE, "\n".join(sorted(files)))
    if sha:
        _write(_VERSION_FILE, sha)


def _escapes(relative: str) -> bool:
    return relative.startswith(("/", "\\")) or ".." in relative.replace("\\", "/").split("/") or ":" in relative


def _run_setup_update() -> typing.Tuple[bool, str]:
    """`setup.py update` under the interpreter setup recorded, logged to logs/."""
    try:
        with open(repo_path(".wony_setup"), encoding="utf-8-sig") as fh:
            python = json.load(fh).get("python") or sys.executable
    except (OSError, ValueError):
        python = sys.executable
    os.makedirs(repo_path("logs"), exist_ok=True)
    log_path = repo_path("logs", "update.log")
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            code = subprocess.call(
                [python, repo_path("setup.py"), "update"],
                cwd=REPO_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=_SETUP_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
    return code == 0, log_path


# ------------------------------------------------------------------ web page


def download_web_ui(dist_dir: str) -> str:
    """Put the built web page for this version of web/ into `dist_dir`, so
    nobody needs Node.js to have one. Returns "" when it worked, else why not.

    A git checkout gets the build of exactly its own web/ (named by the tree
    hash); a ZIP copy, which is always the newest code, gets the newest build.
    """
    name = _LATEST_WEB
    if _is_git_checkout():
        if _git("status", "--porcelain", "--", "web"):
            return "the web page has local edits, so it has to be built here"
        tree = _git("rev-parse", "HEAD:web")
        if not tree:
            return "couldn't tell which version of the web page this is"
        name = f"wony-web-{tree}.zip"
    try:
        data = _download(f"{_WEB_RELEASE}/{name}")
    except Exception as e:
        return f"no ready-made web page for this version ({e})"

    staging = tempfile.mkdtemp(prefix="wony-web-")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if any(_escapes(member) for member in archive.namelist()):
                return "the downloaded web page was malformed"
            archive.extractall(staging)
        if not os.path.getsize(os.path.join(staging, "index.html")):
            return "the downloaded web page was empty"
        if os.path.isdir(dist_dir):
            shutil.rmtree(dist_dir)
        shutil.move(staging, dist_dir)
    except (OSError, zipfile.BadZipFile) as e:
        return f"the downloaded web page couldn't be unpacked ({e})"
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
    return ""


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
