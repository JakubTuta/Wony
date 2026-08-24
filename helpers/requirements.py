import importlib.util
import os
import typing
from dataclasses import dataclass, field

from helpers.paths import resolve as _resolve_path


@dataclass
class Requirement:
    env_vars: typing.List[str] = field(default_factory=list)
    files: typing.List[str] = field(default_factory=list)
    pip_modules: typing.List[str] = field(default_factory=list)
    check: typing.Optional[typing.Callable[[], bool]] = None
    setup_hint: str = ""


def evaluate(req: Requirement) -> typing.Tuple[bool, str]:
    """Returns (ready, reason). reason is empty string when ready."""
    for var in req.env_vars:
        if not os.getenv(var):
            return False, f"missing env: {var}"

    for path in req.files:
        # Repo-relative, not CWD-relative — the tray starts from wherever
        # Task Scheduler puts it.
        if not os.path.exists(_resolve_path(path)):
            return False, f"missing file: {path}"

    for mod in req.pip_modules:
        if importlib.util.find_spec(mod) is None:
            return False, f"pip module not installed: {mod}"

    if req.check is not None:
        try:
            if not req.check():
                return False, "readiness check failed"
        except Exception as e:
            return False, f"readiness check error: {e}"

    return True, ""
