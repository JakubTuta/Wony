"""Google Drive: find files, read them, and — when "Change my Drive files" is
on — create and edit Google Docs and Sheets.

Reading uses Drive's own export (Docs as Markdown, Sheets as CSV, Slides as
text); other files are downloaded and read with helpers/text_extract.py. Shared
documents are written by other people, so everything read comes back fenced
as third-party text.
"""
import json
import os
import typing

from helpers.accounts import CREDENTIALS_FILE
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement
from helpers.untrusted import wrap

_FOLDER = "application/vnd.google-apps.folder"
_DOC = "application/vnd.google-apps.document"
_SHEET = "application/vnd.google-apps.spreadsheet"
_SLIDES = "application/vnd.google-apps.presentation"
# What each Google format is exported as when read.
_EXPORT = {_DOC: "text/markdown", _SHEET: "text/csv", _SLIDES: "text/plain"}
_KINDS = {
    "doc": [_DOC, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "sheet": [_SHEET, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"],
    "slides": [_SLIDES, "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    "pdf": ["application/pdf"],
    "folder": [_FOLDER],
}
_LIST_FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName))"
_LIST_LIMIT = 10
_READ_CHARS = 6000
# Downloads past this are not read: a 200 MB video is not a document.
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


@register_service(
    module_name="drive",
    requires=Requirement(
        files=[CREDENTIALS_FILE],
        pip_modules=["googleapiclient", "google_auth_oauthlib"],
        setup_hint="Run: python setup.py configure — it sets up Google sign-in.",
    ),
)
class Drive:
    """Google Drive, Docs and Sheets for one or more Google accounts."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def _api(name: str, version: str, account: str) -> typing.Any:
        from helpers import google_auth

        return google_auth.service(name, version, account)

    # ------------------------------------------------------------------ read

    @capture_response
    @method_job
    def find_files(
        self,
        query: str = "",
        kind: typing.Literal["", "doc", "sheet", "slides", "pdf", "folder"] = "",
        view: typing.Literal["list", "read"] = "list",
        file: str = "",
        offset: int = 0,
        account: str = "",
    ) -> str:
        """
        [DRIVE JOB] Finds files in Google Drive by name or by what is written in them,
        and reads one: a Google Doc, Sheet or Slides deck, a PDF or an Office file.

        Args:
            query (str): Words in the file name or contents, e.g. "budget 2025".
            kind (str): Only "doc", "sheet", "slides", "pdf" or "folder" files.
            view (str): "list" (the default) shows matching files; "read" returns the
                text of the best match.
            file (str): When reading, the file's name or id (otherwise the best match
                for query).
            offset (int): When reading, where to continue a long file.
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching files, or the file's text.
        """
        if (view or "list") == "read":
            return self._read(file or query, kind, max(0, int(offset or 0)), account)
        files = self._search(query, kind, account)
        if not files:
            return f"No Drive files match '{query}'." if query else "Your Drive has no files to show."
        lines = []
        for f in files:
            owner = ", ".join(o.get("displayName", "") for o in f.get("owners", []))
            lines.append(
                f"- {f['name']} ({_kind_name(f['mimeType'])}, changed {f.get('modifiedTime', '')[:10]}"
                + (f", owner {owner}" if owner else "") + f") id={f['id']}"
            )
        # File names in a shared drive are chosen by whoever shared them.
        return f"Drive files{f' matching {query!r}' if query else ''}:\n" + wrap("\n".join(lines), "drive")

    def _search(self, query: str, kind: str, account: str, limit: int = _LIST_LIMIT) -> typing.List[dict]:
        terms = ["trashed = false"]
        if query:
            q = query.replace("\\", "\\\\").replace("'", "\\'")
            terms.append(f"(name contains '{q}' or fullText contains '{q}')")
        if kind:
            terms.append("(" + " or ".join(f"mimeType = '{m}'" for m in _KINDS[kind]) + ")")
        params: typing.Dict[str, typing.Any] = {
            "q": " and ".join(terms), "pageSize": limit, "fields": _LIST_FIELDS,
            "supportsAllDrives": True, "includeItemsFromAllDrives": True,
        }
        if not query:
            # Drive refuses a sort order on a full-text search.
            params["orderBy"] = "modifiedTime desc"
        result = self._api("drive", "v3", account).files().list(**params).execute()
        return result.get("files", [])

    def _find_one(self, file: str, kind: str, account: str) -> typing.Tuple[typing.Optional[dict], str]:
        """The file meant by a name or id, or why there is not exactly one."""
        if not file:
            return None, "Which file? Give its name."
        api = self._api("drive", "v3", account)
        if " " not in file and len(file) > 20:
            try:
                return api.files().get(fileId=file, fields="id,name,mimeType,size,webViewLink",
                                       supportsAllDrives=True).execute(), ""
            except Exception:
                pass  # not an id after all; search by name
        matches = self._search(file, kind, account, limit=5)
        exact = [f for f in matches if f["name"].lower() == file.lower()]
        if len(exact) == 1 or len(matches) == 1:
            return (exact or matches)[0], ""
        if not matches:
            return None, f"No Drive file called '{file}'."
        # File names in a shared drive are chosen by whoever shared them.
        names = "; ".join(f"{m['name']} (id={m['id']})" for m in matches)
        return None, f"Several files match '{file}': {wrap(names, 'drive')}. Which one?"

    def _read(self, file: str, kind: str, offset: int, account: str) -> str:
        found, problem = self._find_one(file, kind, account)
        if found is None:
            return problem
        name = wrap(found["name"], "drive")
        text = self._text_of(found, account)
        if not text.strip():
            return f"I couldn't read any text in '{name}' — it may be an image, a scan or a format I can't read."
        page = text[offset:offset + _READ_CHARS]
        end = offset + len(page)
        more = f"\n[Characters {offset}–{end} of {len(text)}. Read on with offset={end}.]" if end < len(text) else ""
        return f"'{name}':\n{wrap(page, 'drive')}{more}"

    def _text_of(self, meta: dict, account: str) -> str:
        from helpers.text_extract import extract_bytes

        api = self._api("drive", "v3", account).files()
        mime = meta["mimeType"]
        if mime in _EXPORT:
            data = api.export(fileId=meta["id"], mimeType=_EXPORT[mime]).execute()
            return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        if mime.startswith("application/vnd.google-apps"):
            return ""  # forms, drawings, shortcuts: nothing to read as text
        if int(meta.get("size") or 0) > _MAX_DOWNLOAD_BYTES:
            return ""
        data = api.get_media(fileId=meta["id"], supportsAllDrives=True).execute()
        return extract_bytes(data, meta["name"], mime)

    # ------------------------------------------------------------------ write

    @staticmethod
    def _write_allowed() -> bool:
        return bool(Config.get("modules.drive.allow_write", False))

    @capture_response
    @method_job(confirms=True)
    def edit_file(
        self,
        action: typing.Literal["create_doc", "append", "replace_text", "add_rows", "update_cells", "upload"],
        file: str = "",
        title: str = "",
        text: str = "",
        find: str = "",
        rows: str = "",
        cells: str = "",
        path: str = "",
        account: str = "",
    ) -> str:
        """
        [DRIVE JOB] Changes Google Drive: creates a Google Doc, adds text to a Doc or
        replaces words in it, adds rows to a Sheet or changes cells, or uploads a file
        from this computer.

        Args:
            action (str): "create_doc", "append", "replace_text", "add_rows",
                "update_cells" or "upload". (required)
            file (str): The Doc or Sheet to change, by name or id.
            title (str): The new Doc's title (create_doc).
            text (str): The text to write — Markdown for create_doc and append; the
                replacement for replace_text.
            find (str): The words to replace (replace_text).
            rows (str): Rows as a JSON list of lists, e.g. '[["Rent", "1200"]]'
                (add_rows, update_cells).
            cells (str): Where to write, e.g. "B2" or "Sheet1!A1:C3" (update_cells).
            path (str): The file on this computer to upload (upload).
            account (str): Google account to use (default: primary).

        Returns:
            str: What changed, or what would have been written while changing is off.
        """
        wanted = (action or "").strip().lower()
        if not self._write_allowed():
            preview = text or rows or path or ""
            return (
                "Changing Drive files is switched off. Turn on 'Change my Drive files' in "
                "Settings to allow it." + (f"\nWhat I would have written:\n{preview}" if preview else "")
            )
        if wanted == "create_doc":
            return self._create_doc(title, text, account)
        if wanted == "upload":
            return self._upload(path, account)
        if wanted in ("append", "replace_text"):
            return self._edit_doc(wanted, file, text, find, account)
        if wanted in ("add_rows", "update_cells"):
            return self._edit_sheet(wanted, file, rows, cells, account)
        return f"Unknown action '{action}'. Use create_doc, append, replace_text, add_rows, update_cells or upload."

    def _create_doc(self, title: str, text: str, account: str) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        if not title:
            return "Error: What should the new Doc be called?"
        # Drive converts uploaded Markdown into a real Google Doc.
        media = MediaInMemoryUpload((text or "").encode("utf-8"), mimetype="text/markdown")
        created = self._api("drive", "v3", account).files().create(
            body={"name": title, "mimeType": _DOC}, media_body=media, fields="id,webViewLink",
        ).execute()
        return f"Created the Doc '{title}': {created.get('webViewLink', '')}"

    def _upload(self, path: str, account: str) -> str:
        from googleapiclient.http import MediaFileUpload

        from modules.desktop import _resolve_file

        resolved, matches = _resolve_file(path)
        if resolved is None:
            return f"Several files match '{path}'." if matches else f"No file called '{path}' on this computer."
        if os.path.isdir(resolved):
            return "That's a folder — upload files one at a time."
        created = self._api("drive", "v3", account).files().create(
            body={"name": os.path.basename(resolved)}, media_body=MediaFileUpload(resolved),
            fields="id,webViewLink",
        ).execute()
        return f"Uploaded '{os.path.basename(resolved)}': {created.get('webViewLink', '')}"

    def _edit_doc(self, action: str, file: str, text: str, find: str, account: str) -> str:
        found, problem = self._find_one(file, "doc", account)
        if found is None:
            return problem
        if found["mimeType"] != _DOC:
            return f"'{found['name']}' isn't a Google Doc, so I can't edit it in place."
        if not text and action == "append":
            return "Error: What should I add?"
        docs = self._api("docs", "v1", account).documents()
        if action == "replace_text":
            if not find:
                return "Error: Which words should I replace?"
            request = {"replaceAllText": {"containsText": {"text": find, "matchCase": False}, "replaceText": text}}
            reply = docs.batchUpdate(documentId=found["id"], body={"requests": [request]}).execute()
            changed = (reply.get("replies") or [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
            return f"Replaced {changed} occurrence(s) of '{find}' in '{found['name']}'."
        end = docs.get(documentId=found["id"], fields="body(content(endIndex))").execute()
        index = max(1, (end["body"]["content"][-1]["endIndex"]) - 1)
        request = {"insertText": {"location": {"index": index}, "text": "\n" + text}}
        docs.batchUpdate(documentId=found["id"], body={"requests": [request]}).execute()
        return f"Added the text to the end of '{found['name']}'."

    def _edit_sheet(self, action: str, file: str, rows: str, cells: str, account: str) -> str:
        found, problem = self._find_one(file, "sheet", account)
        if found is None:
            return problem
        if found["mimeType"] != _SHEET:
            return f"'{found['name']}' isn't a Google Sheet, so I can't edit it in place."
        values = _parse_rows(rows)
        if not values:
            return 'Error: Give the rows as a JSON list of lists, e.g. [["Rent", "1200"]].'
        sheet = self._api("sheets", "v4", account).spreadsheets().values()
        body = {"values": values}
        if action == "add_rows":
            sheet.append(spreadsheetId=found["id"], range="A1", valueInputOption="USER_ENTERED",
                         insertDataOption="INSERT_ROWS", body=body).execute()
            return f"Added {len(values)} row(s) to '{found['name']}'."
        if not cells:
            return "Error: Which cells? e.g. B2 or Sheet1!A1:C3."
        sheet.update(spreadsheetId=found["id"], range=cells, valueInputOption="USER_ENTERED", body=body).execute()
        return f"Updated {cells} in '{found['name']}'."

def _kind_name(mime: str) -> str:
    for name, mimes in _KINDS.items():
        if mime in mimes:
            return name
    return mime.rsplit("/", 1)[-1]


def _parse_rows(rows: str) -> typing.List[typing.List[str]]:
    try:
        parsed = json.loads(rows)
    except (json.JSONDecodeError, TypeError):
        # One row per line, cells split by | — what a model writes when it forgets JSON.
        return [[cell.strip() for cell in line.split("|")] for line in (rows or "").splitlines() if line.strip()]
    if isinstance(parsed, list) and parsed and not isinstance(parsed[0], list):
        parsed = [parsed]
    return [[str(cell) for cell in row] for row in parsed] if isinstance(parsed, list) else []
