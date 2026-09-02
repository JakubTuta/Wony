"""Edit config.yaml in place, keeping its comments.

config.yaml is a file people read and hand-edit: the comments in it are half of
what makes it usable. Loading it with a YAML library and dumping it back would
throw every one of them away, so this walks the lines and rewrites only the
values it was asked to change.

Stdlib only — setup.py uses it before any dependency is installed.
"""
import io
import os
import typing

INDENT = "  "


def _line_key(line: str) -> typing.Optional[typing.Tuple[int, str]]:
    """(indent, key) for a `key:` line, else None for blanks, comments, list items."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "-")) or ":" not in stripped:
        return None
    return len(line) - len(line.lstrip(" ")), stripped.split(":", 1)[0].strip()


def _block_end(lines: typing.List[str], header: int, indent: int) -> int:
    """Index just past the last non-blank child of the block headed at `header`."""
    cursor = header + 1
    end = cursor
    while cursor < len(lines):
        line = lines[cursor]
        stripped = line.strip()
        own_indent = len(line) - len(line.lstrip(" "))
        if stripped and not stripped.startswith("#") and own_indent <= indent:
            break
        cursor += 1
        if stripped:
            end = cursor
    return end


def _find_key(
    lines: typing.List[str], key: str, indent: int, start: int, end: int
) -> typing.Optional[int]:
    for i in range(start, min(end, len(lines))):
        if _line_key(lines[i]) == (indent, key):
            return i
    return None


def format_value(value: typing.Any) -> str:
    """Render a scalar the way a person would have typed it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if text == "" or text.lower() in ("true", "false", "null", "yes", "no", "on", "off"):
        return f'"{text}"'
    if any(ch in text for ch in ':#\n"\'{}[]&*!|>%@`,') or text != text.strip():
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    try:
        float(text)
        return f'"{text}"'  # keep "1.0" a string, not a number
    except ValueError:
        return text


def _trailing_comment(line: str) -> str:
    """The ` # ...` a person wrote after a value, so rewriting keeps their note."""
    _, _, after = line.partition(":")
    quotes = after.count('"') + after.count("'")
    if "#" not in after or quotes % 2:
        return ""
    return "  " + after[after.index("#"):].strip()


def _render(key: str, value: typing.Any, indent: int, comment: str = "") -> typing.List[str]:
    pad = " " * indent
    if isinstance(value, (list, tuple)):
        item_pad = pad + INDENT
        return [f"{pad}{key}:\n"] + [f"{item_pad}- {item}\n" for item in value]
    return [f"{pad}{key}: {format_value(value)}{comment}\n"]


def set_value(lines: typing.List[str], dotted_key: str, value: typing.Any) -> None:
    """Set one dotted key in `lines`, creating any parent block that is missing."""
    parts = dotted_key.split(".")
    start, end, indent = 0, len(lines), 0

    for depth, part in enumerate(parts):
        at = _find_key(lines, part, indent, start, end)

        if depth == len(parts) - 1:
            comment = _trailing_comment(lines[at]) if at is not None else ""
            block = _render(part, value, indent, comment)
            if at is None:
                lines[end:end] = block
            else:
                lines[at : _block_end(lines, at, indent)] = block
            return

        if at is None:
            # A brand new top-level section reads better with air around it.
            spacer = ["\n"] if indent == 0 and end > 0 and lines[end - 1].strip() else []
            lines[end:end] = spacer + [f"{' ' * indent}{part}:\n"]
            at = end + len(spacer)
        start, end = at + 1, _block_end(lines, at, indent)
        indent += len(INDENT)


def update(path: str, updates: typing.Dict[str, typing.Any]) -> typing.List[str]:
    """Apply `updates` (dotted key -> value) to the YAML file at `path`.

    Returns the keys written. A list value replaces the whole list, which is what
    "these are the modules I want" means.
    """
    if not os.path.exists(path):
        return []

    with io.open(path, "r", encoding="utf-8-sig") as handle:
        lines = handle.readlines()
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    for dotted_key, value in updates.items():
        set_value(lines, dotted_key, value)

    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
    return list(updates)
