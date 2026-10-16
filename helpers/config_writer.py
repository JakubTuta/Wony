"""Edit config.yaml in place, keeping its comments.

config.yaml is a file people read and hand-edit: the comments in it are half of
what makes it usable. Loading it with a YAML library and dumping it back would
throw every one of them away, so this walks the lines and rewrites only the
values it was asked to change.

Stdlib only — setup.py uses it before any dependency is installed.
"""
import io
import json
import os
import re
import typing

INDENT = "  "

# Line breaks to YAML even inside quotes, so a value holding one must be
# quoted and escaped, never written raw.
_YAML_LINE_BREAKS = (chr(0x85), chr(0x2028), chr(0x2029))

# `- name  # description`, or the same switched off: `# - name  # description`.
_LIST_LINE = re.compile(r"^\s*(#\s*)?-\s+(\S+)\s*(?:#\s*(.*?))?\s*$")

# What follows `key:` when the text sits on the lines below: `>`, `|-`, `>+2`, ...
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?[1-9]?[+-]?\s*(?:#.*)?$")


def _line_key(line: str) -> typing.Optional[typing.Tuple[int, str]]:
    """(indent, key) for a `key:` line, else None for blanks, comments, list items."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "-")) or ":" not in stripped:
        return None
    return len(line) - len(line.lstrip(" ")), stripped.split(":", 1)[0].strip()


def _block_end(lines: typing.List[str], header: int, indent: int) -> int:
    """Index just past the last real child of the block headed at `header`.

    Trailing comments are left out: a comment sitting at the bottom of a block
    introduces whatever comes next, and rewriting the block over it deletes
    documentation the user never asked to lose.
    """
    cursor = header + 1
    end = cursor
    while cursor < len(lines):
        line = lines[cursor]
        stripped = line.strip()
        own_indent = len(line) - len(line.lstrip(" "))
        if stripped and not stripped.startswith("#") and own_indent <= indent:
            break
        cursor += 1
        if stripped and not stripped.startswith("#"):
            end = cursor
    return end


def _scalar_block_end(lines: typing.List[str], at: int, indent: int) -> int:
    """Index just past the text lines of a `>` or `|` scalar headed at `at`.

    Its text is every following line indented deeper than the key (blank lines
    included), whatever it looks like: a line reading `**Role**: ...` is prose
    here, not a key. Blank lines after the last text line are left for whatever
    follows.
    """
    end = at + 1
    cursor = at + 1
    while cursor < len(lines):
        line = lines[cursor]
        if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
            break
        cursor += 1
        if line.strip():
            end = cursor
    return end


def _entry_end(lines: typing.List[str], at: int, indent: int) -> int:
    """Index just past what a new scalar at `at` should replace.

    A plain scalar owns exactly its own line — the comments under it belong to
    the next key. A `>` or `|` scalar owns its text lines too. A key that heads
    a nested block owns the block, and the new value replaces the lot.
    """
    _, _, after = lines[at].partition(":")
    value = after.strip()
    if not value or value.startswith("#"):
        return _block_end(lines, at, indent)
    if _BLOCK_SCALAR.match(value):
        return _scalar_block_end(lines, at, indent)
    return at + 1


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
    needs_quoting = (
        text == ""
        or text.lower() in ("true", "false", "null", "yes", "no", "on", "off")
        or text != text.strip()
        or any(ch in text for ch in ':#\n"\'{}[]&*!|>%@`,')
        or any(ord(ch) < 0x20 for ch in text)
        or any(ch in text for ch in _YAML_LINE_BREAKS)
    )
    if needs_quoting:
        # json's string escaping is a valid subset of YAML's double-quoted
        # style and covers every control character, not just the handful a
        # hand-rolled replace() chain happened to list — a raw \r or \t left
        # unescaped there could otherwise be read as a line break by some
        # YAML parsers and break out of the quotes entirely.
        # Not ensure_ascii: it writes an emoji as two surrogate escapes, which
        # YAML reads back as two broken characters.
        quoted = json.dumps(text, ensure_ascii=False)
        for ch in _YAML_LINE_BREAKS:
            quoted = quoted.replace(ch, f"\\u{ord(ch):04x}")
        return quoted
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


def _list_entry(line: str) -> typing.Optional[typing.Tuple[str, bool, str]]:
    """(name, switched on, description) for a list line, else None."""
    match = _LIST_LINE.match(line)
    if not match:
        return None
    switched_off, name, description = match.groups()
    return name, not switched_off, description or ""


def _list_end(lines: typing.List[str], header: int) -> int:
    """Index just past a list's lines, switched-off options included."""
    end = header + 1
    while end < len(lines) and _list_entry(lines[end]):
        end += 1
    return end


def _render_list(
    key: str, items: typing.Sequence[typing.Any], indent: int, old: typing.List[str]
) -> typing.List[str]:
    """A list with one line per option: the wanted ones, then the others as
    comments. A description written on the old lines moves to the new one, so
    switching an option on or off never leaves a second copy of it behind."""
    descriptions: typing.Dict[str, str] = {}
    for line in old:
        name, _, description = _list_entry(line)  # type: ignore[misc]
        descriptions[name] = descriptions.get(name) or description

    wanted = [str(item) for item in dict.fromkeys(items)]
    pad = " " * indent + INDENT

    def render(name: str, on: bool) -> str:
        description = descriptions.get(name, "")
        text = f"- {name:<14} # {description}" if description else f"- {name}"
        return f"{pad}{'' if on else '# '}{text}\n"

    return (
        [f"{' ' * indent}{key}:\n"]
        + [render(name, True) for name in wanted]
        + [render(name, False) for name in descriptions if name not in wanted]
    )


def _set_list(
    lines: typing.List[str],
    key: str,
    items: typing.Sequence[typing.Any],
    indent: int,
    at: typing.Optional[int],
    end: int,
) -> None:
    if at is None:
        lines[end:end] = _render_list(key, items, indent, [])
        return
    stop = _list_end(lines, at)
    lines[at:stop] = _render_list(key, items, indent, lines[at + 1 : stop])


def _render(key: str, value: typing.Any, indent: int, comment: str = "") -> typing.List[str]:
    return [f"{' ' * indent}{key}: {format_value(value)}{comment}\n"]


def set_value(lines: typing.List[str], dotted_key: str, value: typing.Any) -> None:
    """Set one dotted key in `lines`, creating any parent block that is missing."""
    parts = dotted_key.split(".")
    start, end, indent = 0, len(lines), 0

    for depth, part in enumerate(parts):
        at = _find_key(lines, part, indent, start, end)

        if depth == len(parts) - 1:
            if isinstance(value, (list, tuple)):
                _set_list(lines, part, value, indent, at, end)
                return
            comment = _trailing_comment(lines[at]) if at is not None else ""
            block = _render(part, value, indent, comment)
            if at is None:
                lines[end:end] = block
            else:
                lines[at : _entry_end(lines, at, indent)] = block
            return

        if at is None:
            # A brand new top-level section reads better with air around it.
            spacer = ["\n"] if indent == 0 and end > 0 and lines[end - 1].strip() else []
            lines[end:end] = spacer + [f"{' ' * indent}{part}:\n"]
            at = end + len(spacer)
        start, end = at + 1, _block_end(lines, at, indent)
        indent += len(INDENT)


def _comment_start(lines: typing.List[str], at: int, indent: int) -> int:
    """First line of the comment block sitting directly on top of line `at`."""
    start = at
    while start > 0:
        above = lines[start - 1]
        own_indent = len(above) - len(above.lstrip(" "))
        if not above.strip().startswith("#") or own_indent != indent:
            break
        start -= 1
    return start


def _has_children(lines: typing.List[str], header: int, indent: int) -> bool:
    return _block_end(lines, header, indent) > header + 1


def remove_value(lines: typing.List[str], dotted_key: str) -> bool:
    """Delete one dotted key with its block and the comment above it.

    A parent block left with nothing in it goes too, so retiring the last key
    of a section does not leave a dangling `section:` line behind.
    """
    parts = dotted_key.split(".")
    start, end, indent = 0, len(lines), 0
    headers: typing.List[typing.Tuple[int, int]] = []
    for depth, part in enumerate(parts):
        at = _find_key(lines, part, indent, start, end)
        if at is None:
            return False
        if depth < len(parts) - 1:
            headers.append((at, indent))
            start, end = at + 1, _block_end(lines, at, indent)
            indent += len(INDENT)
            continue
        stop = _block_end(lines, at, indent) if _has_children(lines, at, indent) else at + 1
        start = _comment_start(lines, at, indent)
        del lines[start:stop]
        _drop_double_blank(lines, start)

    for header, header_indent in reversed(headers):
        if _has_children(lines, header, header_indent):
            break
        start = _comment_start(lines, header, header_indent)
        del lines[start : header + 1]
        _drop_double_blank(lines, start)
    return True


def _drop_double_blank(lines: typing.List[str], at: int) -> None:
    """A removed section leaves its spacer line next to the next one's."""
    while 0 < at < len(lines) and not lines[at].strip() and not lines[at - 1].strip():
        del lines[at]


def _parses(text: str) -> typing.Optional[bool]:
    """Whether `text` is valid YAML; None while PyYAML is not installed (setup
    runs before it is)."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return True


def _save(path: str, original: typing.List[str], lines: typing.List[str]) -> None:
    """Write the edited lines, unless the edit turned a readable file into an
    unreadable one. A writer that misjudges the file's layout should fail here,
    with the file untouched, not at the next start with the user's settings
    half-overwritten."""
    if _parses("".join(original)) is True and _parses("".join(lines)) is False:
        raise ValueError("That change would have left config.yaml unreadable, so nothing was written.")
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)


def remove(path: str, dotted_keys: typing.Iterable[str]) -> typing.List[str]:
    """Delete `dotted_keys` from the YAML file at `path`. Returns those removed."""
    if not os.path.exists(path):
        return []
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        lines = handle.readlines()
    original = list(lines)
    removed = [key for key in dotted_keys if remove_value(lines, key)]
    if removed:
        _save(path, original, lines)
    return removed


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

    original = list(lines)
    for dotted_key, value in updates.items():
        set_value(lines, dotted_key, value)

    _save(path, original, lines)
    return list(updates)
