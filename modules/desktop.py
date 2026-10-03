import os
import subprocess
import typing

from helpers.decorators import capture_response
from helpers.paths import repo_path
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement
from helpers.untrusted import wrap


def _desktop_requirement() -> Requirement:
    return Requirement(
        pip_modules=["pyautogui", "pygetwindow", "pyperclip"],
        setup_hint="Run install.bat again and tick Desktop control.",
    )


def _actions_allowed() -> bool:
    from helpers.config import Config
    return bool(Config.get("modules.desktop.allow_actions", False))


def _require_actions(action: str) -> typing.Optional[str]:
    from helpers.turn_context import at_machine, user_present

    # A request from a phone has nobody at the keyboard to see a click land.
    if user_present() and not at_machine():
        return f"Action '{action}' only works when you ask at this computer, not from a chat."
    if not _actions_allowed():
        from helpers.settings import where

        return (
            f"Action '{action}' is disabled. "
            f"Turn on {where('modules.desktop.allow_actions')} to let Wony "
            "act on this computer — typing, clicking, changing windows, writing "
            "the clipboard, and opening or writing files."
        )
    return None


_SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".git", ".venv"}

# How much of the clipboard is read back. A tuning knob: past this, a spoken
# read-out drags and the model is paying tokens for a wall of pasted text.
_CLIPBOARD_PREVIEW_CHARS = 500

# One page of a text file. Same reasoning (and roughly the same size) as
# web._MAX_CONTENT_CHARS: past this the model is paying for text nobody asked
# to hear. `offset` reads the next page.
_MAX_FILE_CHARS = 6000

# Entries listed for a folder before the listing is truncated.
_MAX_DIR_ENTRIES = 100


def _resolve_app_by_name(name: str) -> typing.Optional[str]:
    """An installed program found by name — on PATH or in the App Paths
    registry (how Windows resolves 'chrome', 'spotify', …) — never a literal
    path. "Open spotify" must not be able to resolve to an arbitrary file the
    user happens to have lying around with that name; that risk belongs to
    the file-path branch in `open`, which confirms for dangerous extensions.

    Avoids handing a bare name to ShellExecute (os.startfile), which pops a
    Windows error dialog on failure. Returns the full path, or None if
    unresolved.
    """
    import shutil

    found = shutil.which(name)
    if found:
        return found

    import winreg

    key = name if name.lower().endswith(".exe") else f"{name}.exe"
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{key}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as k:
                path, _ = winreg.QueryValueEx(k, "")  # default value = exe path
                path = os.path.expandvars(path).strip('"')
                if path and os.path.exists(path):
                    return path
        except OSError:
            continue
    return None


def active_window_title() -> str:
    """Title of the window in front, or "" when there is none.

    Not a job: the model is given this as turn context (see modules/ai.py) so
    that "what does this mean" has a subject, and one more tool for a string
    the prompt can carry for free is a bad trade.
    """
    import pygetwindow as gw

    # getActiveWindow() returns None on a locked screen or between focus
    # changes, and raises on some window managers rather than returning None.
    try:
        window = gw.getActiveWindow()
    except Exception:
        return ""
    title = getattr(window, "title", "") or ""
    return title.strip()


def _box_center(box: typing.Dict[str, typing.Tuple[int, int]]) -> typing.Tuple[int, int]:
    left, top = box["top_left"]
    right, bottom = box["bottom_right"]
    return (left + right) // 2, (top + bottom) // 2


def _known_dirs(include_home: bool = True) -> typing.List[str]:
    """Common user folders to resolve bare filenames against.

    Includes OneDrive-redirected variants (Win11 commonly moves Desktop/
    Documents under %USERPROFILE%\\OneDrive). Order = search priority.

    include_home=False drops the catch-all home folder itself. Bare-name
    search wants it — the home folder is a reasonable last resort for
    finding a file by name. The read-confirm gate (_file_needs_confirm) does
    not: "within the home folder" is nearly every file a user has, not the
    handful of places they would expect Wony to read without being asked.
    """
    home = os.path.expanduser("~")
    onedrive = os.environ.get("OneDrive") or os.path.join(home, "OneDrive")
    candidates = [
        os.getcwd(),
        os.path.join(home, "Desktop"),
        os.path.join(onedrive, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(onedrive, "Documents"),
        os.path.join(home, "Downloads"),
    ]
    if include_home:
        candidates.append(home)
    seen: typing.List[str] = []
    for d in candidates:
        if d and os.path.isdir(d) and d not in seen:
            seen.append(d)
    return seen


def _contains(directory: str, path: str) -> bool:
    directory = os.path.normcase(os.path.abspath(directory))
    path = os.path.normcase(os.path.abspath(path))
    return path == directory or path.startswith(directory + os.sep)


_SECRET_PATHS = [
    repo_path(".env"), repo_path("credentials"), repo_path("cache.json"),
    repo_path("wony.db"), repo_path("logs"), repo_path("config.yaml"),
]


def _is_wony_secret(path: str) -> bool:
    """Wony's own config, credentials, cache and logs — off limits to the file
    job no matter the action, confirmed or not."""
    expanded = os.path.abspath(os.path.expanduser(path))
    return any(_contains(secret, expanded) for secret in _SECRET_PATHS)


def _within_known_dirs(path: str) -> bool:
    return any(_contains(d, path) for d in _known_dirs(include_home=False))


_FIND_LIMIT = 20


def _indexed_search(query: str, folder: str = "") -> typing.List[str]:
    """Files whose name or contents match, from the Windows Search index —
    the same index the Start menu search uses. Raises when it is unavailable."""
    import win32com.client

    words = query.replace("'", "''")
    # LIKE treats % _ [ as patterns; brackets make them literal.
    like = "".join(f"[{ch}]" if ch in "%_[" else ch for ch in words)
    scope = "file:" + folder.replace("\\", "/") if folder else "file:"
    sql = (
        f"SELECT TOP {_FIND_LIMIT} System.ItemUrl FROM SystemIndex "
        f"WHERE SCOPE='{scope}' AND (FREETEXT('{words}') OR System.FileName LIKE '%{like}%') "
        "ORDER BY System.Search.Rank DESC"
    )
    connection = win32com.client.Dispatch("ADODB.Connection")
    connection.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
    records = win32com.client.Dispatch("ADODB.Recordset")
    records.Open(sql, connection)
    found = []
    try:
        while not records.EOF:
            url = str(records.Fields.Item("System.ItemUrl").Value or "")
            if url.startswith("file:"):
                found.append(os.path.normpath(url[len("file:"):]))
            records.MoveNext()
    finally:
        records.Close()
        connection.Close()
    return found


def _name_search(query: str, roots: typing.List[str]) -> typing.List[str]:
    needle = query.lower()
    matches: typing.List[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
            for entry in filenames + dirnames:
                if needle in entry.lower():
                    full = os.path.join(dirpath, entry)
                    if full not in matches:
                        matches.append(full)
                        if len(matches) >= _FIND_LIMIT:
                            return matches
    return matches


def _resolve_file(path: str) -> typing.Tuple[typing.Optional[str], typing.List[str]]:
    """Resolve a path or bare filename to an existing file.

    Returns (resolved_path, matches). If exactly one file is found,
    resolved_path is set. If multiple ambiguous matches, resolved_path is
    None and matches holds them. If none, both are empty.
    Matches by exact name (case-insensitive); if the input has no extension,
    also matches files whose stem equals the input.
    """
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        return os.path.abspath(expanded), []

    # Absolute/relative path that doesn't exist and isn't a bare name → give up.
    if os.path.dirname(path):
        return None, []

    needle = path.lower()
    stem_only = "." not in needle
    matches: typing.List[str] = []
    for d in _known_dirs():
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for fname in entries:
            full = os.path.join(d, fname)
            if not os.path.isfile(full):
                continue
            lname = fname.lower()
            if lname == needle or (stem_only and os.path.splitext(lname)[0] == needle):
                matches.append(full)

    # Dedupe preserving order.
    uniq: typing.List[str] = []
    for m in matches:
        if m not in uniq:
            uniq.append(m)

    if len(uniq) == 1:
        return uniq[0], uniq
    return None, uniq


_DANGEROUS_OPEN_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".lnk", ".url", ".hta", ".msi", ".scr",
}


def _open_needs_confirm(args: typing.Dict[str, typing.Any]) -> bool:
    """Opening an installed app by name is routine. Opening something that
    resolves to an executable or script by path is how a downloaded .exe or
    .bat someone was told to "open" would run — that always asks first."""
    target = str(args.get("target", "")).strip()
    if not target or _resolve_app_by_name(target) is not None:
        return False
    resolved, _ = _resolve_file(target)
    if resolved is None:
        return False
    return os.path.splitext(resolved)[1].lower() in _DANGEROUS_OPEN_EXTENSIONS


def _file_needs_confirm(args: typing.Dict[str, typing.Any]) -> bool:
    """Writing always asks. Reading asks only when the path falls outside the
    common user folders and the user did not type it themselves this
    conversation — a page or email that names an arbitrary path must not read
    it silently, but "read my resume on the Desktop" should not interrupt."""
    wanted = str(args.get("action", "read")).strip().lower()
    if wanted in ("write", "append"):
        return True
    if wanted != "read":
        return False

    path = str(args.get("path", "")).strip()
    if not path:
        return False
    resolved, _ = _resolve_file(path)
    if resolved is None or _within_known_dirs(resolved):
        return False

    from helpers.conversation import Conversation
    from helpers.turn_context import user_text

    said = [user_text()] + [m["content"] for m in Conversation.get_messages() if m["role"] == "user"]
    needle = path.lower()
    return not any(needle in str(text).lower() for text in said)


@register_service(
    module_name="desktop",
    requires=_desktop_requirement(),
)
class Desktop:

    # ------------------------------------------------------------------ read-only (always allowed)

    @method_job(confirms={"close"})
    @capture_response
    def manage_window(
        self,
        action: typing.Literal["list", "focus", "minimize", "maximize", "close"] = "list",
        title: str = "",
    ) -> str:
        """
        [DESKTOP JOB] Works with the open application windows: lists them, or brings
        one to the front, minimises, maximises or closes it by (partial) title.
        Everything but listing needs desktop actions switched on.

        Args:
            action (str): "list" (the default), "focus", "minimize", "maximize"
                or "close".
            title (str): Part of the window title, case-insensitive.
                (required for everything except "list")

        Returns:
            str: The window list, or confirmation of what changed.
        """
        import pygetwindow as gw

        wanted = (action or "list").strip().lower()

        if wanted in ("list", "show"):
            windows = [w.title for w in gw.getAllWindows() if w.title.strip()]
            if not windows:
                return "No visible windows found."
            listing = "\n".join(f"  - {w}" for w in sorted(set(windows)))
            return "Open windows:\n" + wrap(listing, "window titles")

        if wanted not in ("focus", "minimize", "minimise", "maximize", "maximise", "close"):
            return f"Unknown action '{action}'. Use list, focus, minimize, maximize or close."

        # One gate for every window action, rather than per job — focus_window
        # shipped without one for exactly that reason.
        blocked = _require_actions(f"window {wanted}")
        if blocked:
            return blocked
        if not title:
            return f"Error: which window should I {wanted}?"

        needle = title.lower()
        windows = [w for w in gw.getAllWindows() if needle in w.title.lower()]
        if not windows:
            return f"No window found matching '{title}'."

        target = windows[0]
        try:
            if wanted == "focus":
                return self._focus(target)
            if wanted in ("minimize", "minimise"):
                target.minimize()
                return f"Minimised '{target.title}'."
            if wanted in ("maximize", "maximise"):
                target.maximize()
                return f"Maximised '{target.title}'."
            target.close()
            return f"Closed '{target.title}'."
        except Exception as e:
            return f"Could not {wanted} '{target.title}': {e}"

    @staticmethod
    def _focus(target) -> str:
        try:
            if getattr(target, "isMinimized", False):
                target.restore()
            target.activate()
            return f"Focused window: '{target.title}'."
        except Exception:
            # pygetwindow.activate() throws intermittently on Windows; the
            # minimize→restore toggle reliably forces the window forward.
            target.minimize()
            target.restore()
            return f"Focused window: '{target.title}'."

    @method_job(confirms={"write", "set", "copy"})
    @capture_response
    def clipboard(self, action: typing.Literal["read", "write"] = "read", text: str = "") -> str:
        """
        [DESKTOP JOB] Reads what is on the clipboard, or puts text on it.
        Writing needs desktop actions switched on.

        Args:
            action (str): "read" (the default) or "write".
            text (str): What to copy. (required when writing)

        Returns:
            str: The clipboard contents, or confirmation of the copy.
        """
        import pyperclip

        wanted = (action or "read").strip().lower()

        if wanted in ("read", "get", "show"):
            current = pyperclip.paste()
            if not current:
                return "Clipboard is empty."
            preview = current[:_CLIPBOARD_PREVIEW_CHARS]
            suffix = (
                f"\n[… {len(current) - _CLIPBOARD_PREVIEW_CHARS} more chars]"
                if len(current) > _CLIPBOARD_PREVIEW_CHARS
                else ""
            )
            return f"Clipboard content:\n{wrap(preview + suffix, 'clipboard')}"

        if wanted not in ("write", "set", "copy"):
            return f"Unknown action '{action}'. Use read or write."

        blocked = _require_actions("clipboard write")
        if blocked:
            return blocked
        if not text:
            return "Error: No text to copy."

        pyperclip.copy(text)
        preview = text[:80] + ("…" if len(text) > 80 else "")
        return f"Copied to clipboard: '{preview}'"

    @method_job
    @capture_response
    def find_file(self, query: str, search_path: str = "") -> str:
        """
        [DESKTOP JOB] Finds files on this computer by name or by words written inside
        them — "the PDF about my lease", "the spreadsheet with the 2025 budget".

        Args:
            query (str): Part of the file name, or words in the file. (required)
            search_path (str): Only look inside this folder.

        Returns:
            str: Matching file paths, best match first.
        """
        if not query.strip():
            return "Error: What should I look for?"
        folder = os.path.expanduser(search_path) if search_path else ""
        if folder and not os.path.isdir(folder):
            return f"Error: There is no folder {search_path}."

        try:
            matches = _indexed_search(query, folder)
            note = ""
        except Exception:
            # Windows Search is off or unavailable: names only.
            matches = _name_search(query, [folder] if folder else _known_dirs())
            note = "\n(Windows Search isn't available, so I only matched file names, not contents.)"

        if not matches:
            return f"No files match '{query}'.{note}"
        suffix = f"\n(Showing the first {_FIND_LIMIT}.)" if len(matches) >= _FIND_LIMIT else ""
        return f"Files matching '{query}':\n" + "\n".join(f"  {m}" for m in matches) + suffix + note

    @method_job(confirms=_file_needs_confirm)
    @capture_response
    def file(
        self,
        action: typing.Literal["read", "write", "append", "list"] = "read",
        path: str = "",
        content: str = "",
        offset: int = 0,
    ) -> str:
        """
        [DESKTOP JOB] Reads a file's text (PDF and Office documents too), writes or appends text to one, or
        lists what is in a folder. Writing and appending need
        desktop actions switched on.

        Args:
            action (str): "read" (the default), "write", "append" or "list".
            path (str): The file or folder. A bare filename is looked for on the
                Desktop, in Documents and Downloads, in the home folder and the
                current directory. Writing needs a full path. (required)
            content (str): The text to write or append. (required for write and append)
            offset (int): Where to start reading, in characters. Use it to read the
                next part of a file that was cut short.

        Returns:
            str: The file's text, the folder listing, or confirmation of the write.
        """
        wanted = (action or "read").strip().lower()
        if not path:
            return "Error: Which file?"
        if _is_wony_secret(path):
            return "Error: I don't read or write Wony's own config, credentials or logs."

        if wanted == "read":
            return self._read_file(path, offset)
        if wanted == "list":
            return self._list_dir(path)
        if wanted not in ("write", "append"):
            return f"Unknown action '{action}'. Use read, write, append or list."

        blocked = _require_actions(f"file {wanted}")
        if blocked:
            return blocked
        if not content:
            return "Error: No text to write."
        return self._write_file(path, content, append=wanted == "append")

    @staticmethod
    def _read_file(path: str, offset: int) -> str:
        resolved, matches = _resolve_file(path)
        if resolved is None:
            if matches:
                listing = "\n".join(f"  {m}" for m in matches[:20])
                return f"Ambiguous: multiple files match '{path}':\n{listing}"
            return f"Error: No file called '{path}'."
        if _is_wony_secret(resolved):
            return "Error: I don't read or write Wony's own config, credentials or logs."
        if os.path.isdir(resolved):
            return Desktop._list_dir(resolved)

        try:
            with open(resolved, "r", encoding="utf-8") as handle:
                text = handle.read()
        except UnicodeDecodeError:
            from helpers.text_extract import extract_file

            # PDF, Word, PowerPoint, Excel.
            text = extract_file(resolved)
            if not text:
                return f"'{resolved}' isn't a file I can read text from."
        except OSError as e:
            return f"Error reading {resolved}: {e}"

        start = max(0, int(offset or 0))
        if start >= len(text) and text:
            return f"{resolved} has only {len(text)} characters — nothing at offset {start}."

        page = text[start:start + _MAX_FILE_CHARS]
        if not page:
            return f"{resolved} is empty."
        end = start + len(page)
        suffix = (
            f"\n\n[Characters {start}–{end} of {len(text)}. "
            f"Read on with offset={end}.]"
            if end < len(text) else ""
        )
        return f"{resolved}:\n{wrap(page, 'file')}{suffix}"

    @staticmethod
    def _list_dir(path: str) -> str:
        folder = os.path.expanduser(path)
        if not os.path.isdir(folder):
            return f"Error: '{path}' is not a folder."
        if _is_wony_secret(folder):
            return "Error: I don't read or write Wony's own config, credentials or logs."
        try:
            entries = sorted(os.listdir(folder))
        except OSError as e:
            return f"Error listing {folder}: {e}"
        if not entries:
            return f"{folder} is empty."

        lines = []
        for entry in entries[:_MAX_DIR_ENTRIES]:
            marker = "/" if os.path.isdir(os.path.join(folder, entry)) else ""
            lines.append(f"  {entry}{marker}")
        suffix = (
            f"\n(Showing {_MAX_DIR_ENTRIES} of {len(entries)}.)"
            if len(entries) > _MAX_DIR_ENTRIES else ""
        )
        return f"{folder} ({len(entries)} item(s)):\n" + "\n".join(lines) + suffix

    @staticmethod
    def _write_file(path: str, content: str, append: bool) -> str:
        target = os.path.abspath(os.path.expanduser(path))
        if _is_wony_secret(target):
            return "Error: I don't read or write Wony's own config, credentials or logs."
        folder = os.path.dirname(target)
        if folder and not os.path.isdir(folder):
            return f"Error: the folder '{folder}' does not exist."

        existed = os.path.exists(target)
        try:
            with open(target, "a" if append else "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as e:
            return f"Error writing {target}: {e}"

        if append:
            return f"Added {len(content)} characters to {target}."
        return f"{'Overwrote' if existed else 'Wrote'} {target} ({len(content)} characters)."

    # ------------------------------------------------------------------ action-gated

    @method_job(confirms=_open_needs_confirm)
    @capture_response
    def open(self, target: str) -> str:
        """
        [DESKTOP JOB] Opens something on this computer — an application by name
        ('notepad', 'chrome', 'spotify'), or a file or folder, which opens in whatever
        program normally handles it.
        Needs desktop actions switched on.

        Args:
            target (str): An application name, or a full path, or just a filename
                (with or without its extension). Bare filenames are looked for on the
                Desktop, in Documents and Downloads, in the home folder and the current
                directory, including their OneDrive-redirected versions. (required)

        Returns:
            str: Confirmation or error.
        """
        blocked = _require_actions("open")
        if blocked:
            return blocked

        if not target:
            return "Error: Nothing to open."

        # Apps by name first: a bare "spotify" means the installed app, not a
        # stray file of that name. Resolve to a concrete executable BEFORE
        # launching — handing a bare name to ShellExecute pops a premature
        # "cannot find" dialog and reports failure even when the app opens
        # moments later.
        app = _resolve_app_by_name(target)
        if app is not None:
            try:
                subprocess.Popen([app])
                return f"Opening '{target}'."
            except Exception as e:
                return f"Error opening '{target}': {e}"

        resolved, matches = _resolve_file(target)
        if resolved is None:
            if matches:
                listing = "\n".join(f"  {m}" for m in matches[:20])
                return (
                    f"Ambiguous: multiple files match '{target}'. "
                    f"Specify a full path:\n{listing}"
                )
            return (
                f"Error: Could not find an app or file called '{target}'. "
                f"Searched: {', '.join(_known_dirs())}"
            )
        if _is_wony_secret(resolved):
            return "Error: I don't read or write Wony's own config, credentials or logs."

        try:
            os.startfile(resolved)
            return f"Opened: {resolved}"
        except Exception as e:
            return f"Error opening file: {e}"

    @method_job(confirms=True)
    @capture_response
    def type_text(self, text: str) -> str:
        """
        [DESKTOP JOB] Types text into the currently focused application as keyboard input.
        Needs desktop actions switched on.
        Note: works best with ASCII text; unicode characters are handled via clipboard paste.

        Args:
            text (str): Text to type into the active window. (required)

        Returns:
            str: Confirmation.
        """
        blocked = _require_actions("type_text")
        if blocked:
            return blocked

        import pyautogui
        import pyperclip

        try:
            if text.isascii():
                # pyautogui.write() types the keys directly. The clipboard route
                # below is only needed for characters no key produces, and using
                # it for everything silently threw away whatever the user had
                # copied.
                pyautogui.write(text)
            else:
                try:
                    previous = pyperclip.paste()
                except Exception:
                    previous = None
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
                if previous is not None:
                    # Paste is asynchronous in the target app; restoring
                    # immediately can beat it to the clipboard.
                    import time
                    time.sleep(0.2)
                    pyperclip.copy(previous)
        except Exception as e:
            return f"Error typing text: {e}"

        preview = text[:60] + ("…" if len(text) > 60 else "")
        return f"Typed: '{preview}'"

    @method_job(confirms=True)
    @capture_response
    def click(self, text: str = "", x: int = -1, y: int = -1, double: bool = False) -> str:
        """
        [DESKTOP JOB] Clicks on the screen: on words shown there (a button or link by
        its label — prefer this), or at exact pixel coordinates.
        Needs desktop actions switched on.

        Args:
            text (str): The words to click, as they appear on screen.
            x (int): Horizontal pixel coordinate, only when there are no words to click.
            y (int): Vertical pixel coordinate, with x.
            double (bool): Double-click instead of clicking once.

        Returns:
            str: What was clicked, or why nothing was.
        """
        blocked = _require_actions("click")
        if blocked:
            return blocked
        if not text:
            if x < 0 or y < 0:
                return "Error: What should I click? Give the words on screen or x and y."
            return self._click_point(int(x), int(y), double)

        from helpers.screenReader import ScreenReader

        try:
            screenshot = ScreenReader.take_screenshot(target="main")
        except ImportError:
            return (
                "I can't see the screen — screen capture isn't installed. "
                "Run: pip install -r requirements/desktop.txt"
            )

        matches = ScreenReader.find_text_matches(screenshot, text)
        if not matches:
            return f"I couldn't find '{text}' on the screen."

        # Several regions read as the same words, so there is no way to know
        # which one was meant — and a click is not undoable. Say so instead.
        if len(matches) > 1:
            captions = ", ".join(f"'{m['caption']}'" for m in matches[:5])
            return (
                f"'{text}' appears {len(matches)} times on screen ({captions}), "
                "so I didn't click anything. Tell me which one you mean."
            )

        import pyautogui

        x, y = _box_center(matches[0]["box"])
        try:
            pyautogui.click(x, y, clicks=2 if double else 1)
        except Exception as e:
            return f"Error clicking '{text}' at ({x}, {y}): {e}"

        verb = "Double-clicked" if double else "Clicked"
        return f"{verb} '{matches[0]['caption']}' at ({x}, {y})."

    @staticmethod
    def _click_point(x: int, y: int, double: bool) -> str:
        import pyautogui

        try:
            pyautogui.click(x, y, clicks=2 if double else 1)
        except Exception as e:
            return f"Error clicking at ({x}, {y}): {e}"
        return f"{'Double-clicked' if double else 'Clicked'} at ({x}, {y})."
