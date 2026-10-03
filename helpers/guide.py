"""What Wony says about itself, taken from what it actually is.

Nothing here is a canned answer: values and where to change them come from the
live settings (helpers/settings.py), a feature's state from the registry, and
install, setup and troubleshooting steps from README.md — the page the user
reads. Fix the README and Wony says the fixed thing.
"""
import re
import typing

from helpers import lookup, settings
from helpers.paths import repo_path

_GUIDE_FILE = repo_path("README.md")
_HEADING = re.compile(r"^#{1,3} (.+)$")

_MAX_CHUNKS = 8
_MAX_GUIDE_CHARS = 4000  # all one lookup may add to the prompt
_MAX_CHUNK_CHARS = 1200


class _Chunk(typing.NamedTuple):
    heading: str
    text: str
    header: str = ""  # for a table row: the header line that says what its columns mean

    def title(self) -> str:
        """What the chunk is about: its heading and, for a table row, the first cell."""
        first = self.text.strip("| ").split("|")[0] if self.header else ""
        return f"{self.heading} {first}".lower()


def _chunks() -> typing.List[_Chunk]:
    """The guide in pieces a question can be answered from — each paragraph or
    list, and each row of a table — tagged with the heading above it. Empty
    when the guide is missing."""
    try:
        with open(_GUIDE_FILE, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []

    chunks: typing.List[_Chunk] = []
    heading = ""
    block: typing.List[str] = []
    in_code = False

    def flush() -> None:
        if block and block[0].startswith("|"):
            chunks.extend(_Chunk(heading, row, block[0]) for row in block[2:])  # block[1] is |---|
        elif block:
            chunks.append(_Chunk(heading, "\n".join(block)))
        block.clear()

    for line in lines:
        if line.lstrip().startswith("```"):
            if not in_code:
                flush()  # the text above ends where the code starts
            block.append(line)
            in_code = not in_code
            if not in_code:
                flush()  # and the code at its closing fence
            continue
        if in_code:  # a "# comment" in code is not a heading, nor a blank line a break
            block.append(line)
            continue
        match = _HEADING.match(line)
        if match:
            flush()
            heading = match.group(1).strip()
        elif line.strip() in ("", "---"):
            flush()
        else:
            block.append(line)
    flush()
    return chunks


def _clip(text: str) -> str:
    if len(text) <= _MAX_CHUNK_CHARS:
        return text
    return text[:_MAX_CHUNK_CHARS].rsplit("\n", 1)[0] + "\n…"


def search(words: typing.List[str]) -> str:
    """The pieces of the guide that best answer the keywords, in reading order.
    Empty when nothing in it mentions them."""
    chunks = _chunks()
    best = lookup.rank(words, [(f"{chunk.header} {chunk.text}".lower(), chunk.title()) for chunk in chunks])

    picked, used = [], 0
    for index in best[:_MAX_CHUNKS]:
        size = len(_clip(chunks[index].text))
        if picked and used + size > _MAX_GUIDE_CHARS:
            break
        picked.append(index)
        used += size
    if not picked:
        return ""

    out, heading, header = ["From the user guide:"], None, ""
    for index in sorted(picked):
        chunk = chunks[index]
        if chunk.heading != heading:
            out += ["", f"## {chunk.heading}"]
            heading = chunk.heading
        if not chunk.header:
            out.append("")
        elif chunk.header != header:  # rows of one table share its header line
            out += ["", chunk.header]
        header = chunk.header
        out.append(_clip(chunk.text))
    return "\n".join(out)


def headings() -> str:
    names = list(dict.fromkeys(chunk.heading for chunk in _chunks()))
    return "User guide sections: " + ", ".join(names) if names else ""


def answer(query: str) -> str:
    """Everything Wony knows about `query` — settings, features and guide —
    or, when nothing matches, what it can be asked about."""
    words = lookup.keywords(query)
    found = [part for part in (settings.explain(words), search(words)) if part] if words else []
    if found:
        return "\n\n".join(found)

    lead = f"Nothing about '{query.strip()}' in my settings or my guide.\n" if (query or "").strip() else ""
    return "\n".join(part for part in (lead + "What I can look up:", settings.overview(), headings()) if part)
