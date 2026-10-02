"""Edit .env in place, keeping whatever the user already put there.

Mirrors config_writer.py's approach for config.yaml: rewrite only the lines
being changed instead of regenerating the file, so comments and key order
survive. Stdlib only — setup.py uses it before any dependency is installed.
"""
import io
import os
import re
import typing


def read(path: str) -> typing.Dict[str, str]:
    """Every KEY=value pair currently in the .env file at `path`."""
    values: typing.Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, raw = stripped.partition("=")
            values[key.strip()] = raw.strip().strip("\"'")
    return values


def _check_value(key: str, value: str) -> None:
    """Refuse a value that could break out of its quotes and inject a line —
    a stray `"` or newline in a pasted key would otherwise let one update
    plant an arbitrary KEY=value, or truncate/append to the file."""
    if any(ch == '"' or ord(ch) < 0x20 for ch in value):
        raise ValueError(
            f"Value for '{key}' contains a quote or control character and can't be saved to .env."
        )


def update(path: str, updates: typing.Dict[str, str]) -> typing.List[str]:
    """Set KEY=value pairs in the .env file at `path`.

    A key that is only there as a commented-out placeholder is replaced in
    place, so the file stays in the order its comments describe. Returns the
    keys written.

    Raises ValueError without writing anything if any value is unsafe to
    quote (see _check_value) — an all-or-nothing update is simpler to reason
    about than a file left half written.
    """
    for key, value in updates.items():
        _check_value(key, value)

    lines: typing.List[str] = []
    if os.path.exists(path):
        with io.open(path, "r", encoding="utf-8-sig") as handle:
            lines = handle.readlines()
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    for key, value in updates.items():
        rendered = f'{key}="{value}"\n'
        pattern = re.compile(r"^\s*#?\s*" + re.escape(key) + r"\s*=")
        for index, line in enumerate(lines):
            if pattern.match(line):
                lines[index] = rendered
                break
        else:
            lines.append(rendered)

    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
    return list(updates)
