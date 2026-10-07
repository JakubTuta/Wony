"""Every registered job is sent to the model on every request, so the job list
is a token budget and an accuracy budget at once. A new job is a decision, not
an accident.

Counted from the declarations, not the registry: the registry only holds the
modules this machine has switched on, which hid growth in all the others.

Run directly: python tests/test_job_budget.py
"""
import glob
import importlib
import inspect
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# The wall panel's own list, smaller than the PC's: 33 once the watchers became
# triggers, the two power jobs merged, and web, MCP and document indexing were
# removed. +1 undo (reversible changes stopped asking first). Raise it on
# purpose, and say what for.
_JOB_BUDGET = 34


def _is_job(obj) -> bool:
    inner = getattr(obj, "__func__", obj)
    return any(
        getattr(o, "_is_job_method", False) or hasattr(o, "_job_confirms")
        for o in (obj, inner)
    )


def declared_jobs() -> dict:
    """{job name: module file} for every job any module declares."""
    from helpers.config import Config

    Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
    jobs: dict = {}
    for path in sorted(glob.glob(os.path.join(_REPO_ROOT, "modules", "*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if name == "__init__":
            continue
        module = importlib.import_module(f"modules.{name}")
        for attr in vars(module).values():
            if getattr(attr, "__module__", None) != module.__name__:
                continue
            if inspect.isfunction(attr) and _is_job(attr):
                jobs[attr.__name__] = name
            elif inspect.isclass(attr):
                for key, value in vars(attr).items():
                    if _is_job(value):
                        jobs[getattr(value, "_job_name", key)] = name
    return jobs


class TestJobBudget(unittest.TestCase):
    def test_the_job_list_stays_within_budget(self) -> None:
        jobs = declared_jobs()
        self.assertLessEqual(
            len(jobs), _JOB_BUDGET,
            f"{len(jobs)} jobs declared, budget is {_JOB_BUDGET}. If the new job is "
            "right, raise _JOB_BUDGET on purpose and say why.",
        )

    def test_retired_names_stay_gone(self) -> None:
        jobs = declared_jobs()
        for name in ("ask_question", "watch_inbox", "watch_calendar", "power_device",
                     "sleep_device", "manage_documents", "web_search", "fetch_url",
                     "manage_mcp_server"):
            self.assertNotIn(name, jobs)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
