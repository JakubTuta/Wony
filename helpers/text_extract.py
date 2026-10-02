"""Plain text out of a document, whatever it arrived as: a file on disk, a
Drive download, an email attachment.

PDF through pypdf; Word, PowerPoint and Excel through their own zip-of-XML
format with the standard library; anything that is text already as it is. A
format this cannot read comes back as "" — never as binary noise handed to the
model as if it were words.
"""
import io
import os
import re
import typing
import zipfile

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".yaml", ".yml", ".ini", ".py", ".html", ".htm",
}
# The XML parts of an Office file that carry its words, and the tag holding them.
_OFFICE_PARTS = {
    ".docx": (re.compile(r"^word/(document|header\d*|footer\d*)\.xml$"), "w:t"),
    ".pptx": (re.compile(r"^ppt/slides/slide\d+\.xml$"), "a:t"),
    ".xlsx": (re.compile(r"^xl/sharedStrings\.xml$"), "t"),
}
_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def extract_file(path: str) -> str:
    with open(path, "rb") as fh:
        return extract_bytes(fh.read(), os.path.basename(path))


def extract_bytes(data: bytes, name: str = "", mime: str = "") -> str:
    """Text of a document given its bytes and its file name or MIME type."""
    ext = os.path.splitext(name)[1].lower() or _MIME_EXTENSIONS.get(mime, "")
    try:
        if ext == ".pdf":
            return _pdf(data)
        if ext in _OFFICE_PARTS:
            return _office(data, ext)
        if ext in _TEXT_EXTENSIONS or mime.startswith("text/"):
            text = data.decode("utf-8", errors="replace")
            return _strip_tags(text) if ext in (".html", ".htm") or mime == "text/html" else text
    except Exception:
        return ""
    return ""


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _office(data: bytes, ext: str) -> str:
    pattern, tag = _OFFICE_PARTS[ext]
    words = re.compile(rf"<{tag}(?:\s[^>]*)?>([^<]*)</{tag}>")
    paragraphs: typing.List[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for part in sorted(n for n in archive.namelist() if pattern.match(n)):
            xml = archive.read(part).decode("utf-8", errors="replace")
            # One line per paragraph / slide shape, so text does not run together.
            for block in re.split(r"</(?:w:p|a:p|si)>", xml):
                line = "".join(words.findall(block)).strip()
                if line:
                    paragraphs.append(_unescape(line))
    return "\n".join(paragraphs)


def _unescape(text: str) -> str:
    import html

    return html.unescape(text)


def _strip_tags(markup: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", text))).strip()
