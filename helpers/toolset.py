"""Which tools the model gets this turn.

Every tool sent costs tokens on every request and is one more wrong thing to
pick. With few features on, all of them go. With many, the model gets the ones
any turn may need, the features the request is about, and whatever the last
turns used — "yes" and "read it to me" are about those.

Ranked by meaning when the embedding model is loaded (helpers/semantic.py), by
words until then, so the first request never waits for a model to load.
"""
import typing

# Below this many tools, sending all of them beats any risk of leaving one out.
_SELECT_ABOVE = 25
# Features picked by what the request says, on top of the ones always sent.
_TOP_FEATURES = 3
# Any turn may need these. "" is a job registered outside any feature.
_ALWAYS = {"", "employer", "status", "ai", "routines", "scheduler", "notes", "web", "basics"}

_vectors: typing.Dict[str, typing.Any] = {}  # feature text -> its embedding


def pick(text: str, recent_jobs: typing.Iterable[str] = ()) -> typing.Dict[str, typing.Callable]:
    """The jobs to send for a request saying `text`, after turns that used `recent_jobs`."""
    from helpers.registry import ServiceRegistry

    jobs = ServiceRegistry.get_all_jobs()
    if len(jobs) <= _SELECT_ABOVE:
        return jobs
    modules = ServiceRegistry.get_job_modules()
    wanted = set(_ALWAYS) | {modules.get(name, "") for name in recent_jobs}
    candidates = sorted(set(modules.values()) - wanted)
    wanted |= set(_rank(text, candidates, jobs, modules)[:_TOP_FEATURES])
    return {name: func for name, func in jobs.items() if modules.get(name, "") in wanted}


def _describe(module: str, jobs: typing.Dict[str, typing.Callable], modules: typing.Dict[str, str]) -> typing.Tuple[str, str]:
    """(text, title) for one feature: what the user is told about it, and what
    its jobs say about themselves."""
    from helpers.settings import MODULES
    from helpers.tools import _parse_signature

    label, about = module.replace("_", " ").replace("mcp:", ""), ""
    for key, name, description, example in MODULES:
        if key == module:
            label, about = name, f"{description} {example}"
    parts = [about]
    for job_name, func in jobs.items():
        if modules.get(job_name, "") == module:
            try:
                parts.append(f"{job_name.replace('_', ' ')}: {_parse_signature(func)[0]}")
            except Exception:
                parts.append(job_name.replace("_", " "))
    return " ".join(parts).lower(), f"{label} {module}".lower()


def _rank(
    text: str,
    candidates: typing.List[str],
    jobs: typing.Dict[str, typing.Callable],
    modules: typing.Dict[str, str],
) -> typing.List[str]:
    """Candidate features, most relevant to `text` first."""
    entries = [_describe(module, jobs, modules) for module in candidates]
    by_meaning = _rank_by_meaning(text, entries)
    if by_meaning is not None:
        return [candidates[i] for i in by_meaning]

    from helpers import lookup

    return [candidates[i] for i in lookup.rank(lookup.keywords(text), entries)]


def _rank_by_meaning(text: str, entries: typing.List[typing.Tuple[str, str]]) -> typing.Optional[typing.List[int]]:
    """Indexes by embedding similarity, or None while the model is not loaded."""
    from helpers import semantic

    if not semantic.ready():
        semantic.warm()
        return None
    import numpy as np

    try:
        query = np.asarray(semantic.embed(text), dtype=np.float32)
        scores = []
        for body, title in entries:
            key = f"{title}\n{body}"
            if key not in _vectors:
                _vectors[key] = np.asarray(semantic.embed(f"{title}. {body}"), dtype=np.float32)
            vec = _vectors[key]
            scores.append(float(vec @ query) / (float(np.linalg.norm(vec) * np.linalg.norm(query)) or 1.0))
    except Exception:
        return None
    return sorted(range(len(entries)), key=lambda i: scores[i], reverse=True)
