import os
import subprocess
import typing

from helpers.decorators import capture_response
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement


def _desktop_requirement() -> Requirement:
    return Requirement(
        pip_modules=["pyautogui", "pygetwindow", "pyperclip"],
        setup_hint="pip install -r requirements/desktop.txt",
    )


def _actions_allowed() -> bool:
    from helpers.config import Config
    return bool(Config.get("modules.desktop.allow_actions", False))


def _require_actions(action: str) -> typing.Optional[str]:
    if not _actions_allowed():
        return (
            f"Action '{action}' is disabled. "
            "Set modules.desktop.allow_actions: true in config.yaml to let Wony "
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


def _resolve_executable(name: str) -> typing.Optional[str]:
    """Resolve an app name to a launchable executable path, deterministically.

    Avoids handing a bare name to ShellExecute (os.startfile), which pops a
    Windows error dialog on failure. Checks, in order:
      1. an existing path as given,
      2. PATH (shutil.which),
      3. the App Paths registry (how Windows resolves 'chrome', 'spotify', …).
    Returns the full path, or None if unresolved.
    """
    import shutil

    expanded = os.path.expanduser(name)
    if os.path.exists(expanded):
        return os.path.abspath(expanded)

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


def _known_dirs() -> typing.List[str]:
    """Common user folders to resolve bare filenames against.

    Includes OneDrive-redirected variants (Win11 commonly moves Desktop/
    Documents under %USERPROFILE%\\OneDrive). Order = search priority.
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
        home,
    ]
    seen: typing.List[str] = []
    for d in candidates:
        if d and os.path.isdir(d) and d not in seen:
            seen.append(d)
    return seen


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
        Everything but listing requires modules.desktop.allow_actions in config.

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
            return "Open windows:\n" + "\n".join(f"  - {w}" for w in sorted(set(windows)))

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
        Writing requires modules.desktop.allow_actions to be enabled in config.

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
            return f"Clipboard content:\n{preview}{suffix}"

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
    def find_file(self, name: str, search_path: str = "") -> str:
        """
        [DESKTOP JOB] Searches for files matching a name or pattern on the filesystem.
        Searches from the user's home directory by default, or a configured/specified path.

        Args:
            name (str): Filename or partial name to search for (case-insensitive). (required)
            search_path (str): Directory to start searching from. Defaults to home directory.

        Returns:
            str: List of matching file paths found.
        """
        if not name:
            return "Error: No filename provided."

        from helpers.config import Config

        # Explicit path overrides; otherwise search common user folders first
        # (Desktop/Documents/Downloads, incl. OneDrive) then the configured root.
        if search_path:
            roots = [os.path.expanduser(search_path)]
        else:
            roots = list(_known_dirs())
            cfg_root = os.path.expanduser(Config.get("modules.desktop.file_search_root", "~"))
            if cfg_root not in roots:
                roots.append(cfg_root)

        roots = [r for r in roots if os.path.isdir(r)]
        if not roots:
            return f"Error: No valid search path (search_path={search_path!r})."

        needle = name.lower()
        matches: typing.List[str] = []
        seen: typing.Set[str] = set()
        max_results = 20

        for root in roots:
            if len(matches) >= max_results:
                break
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and d not in _SKIP_DIRS
                ]
                # Match folders too (docstring promises locating folders).
                for entry in filenames + dirnames:
                    if needle in entry.lower():
                        full = os.path.join(dirpath, entry)
                        if full not in seen:
                            seen.add(full)
                            matches.append(full)
                            if len(matches) >= max_results:
                                break
                if len(matches) >= max_results:
                    break

        if not matches:
            return f"No files found matching '{name}' under: {', '.join(roots)}."

        suffix = f"\n(Showing first {max_results}; there may be more.)" if len(matches) == max_results else ""
        return f"Found {len(matches)} match(es) for '{name}':\n" + "\n".join(f"  {p}" for p in matches) + suffix

    @method_job(confirms={"write", "append"})
    @capture_response
    def file(
        self,
        action: typing.Literal["read", "write", "append", "list"] = "read",
        path: str = "",
        content: str = "",
        offset: int = 0,
    ) -> str:
        """
        [DESKTOP JOB] Reads a text file's contents, writes or appends text to one, or
        lists what is in a folder. Writing and appending require
        modules.desktop.allow_actions to be enabled in config.

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

        if wanted in ("read", "cat", "show"):
            return self._read_file(path, offset)
        if wanted in ("list", "ls", "dir"):
            return self._list_dir(path)
        if wanted not in ("write", "save", "append", "add"):
            return f"Unknown action '{action}'. Use read, write, append or list."

        blocked = _require_actions(f"file {wanted}")
        if blocked:
            return blocked
        if not content:
            return "Error: No text to write."
        return self._write_file(path, content, append=wanted in ("append", "add"))

    @staticmethod
    def _read_file(path: str, offset: int) -> str:
        resolved, matches = _resolve_file(path)
        if resolved is None:
            if matches:
                listing = "\n".join(f"  {m}" for m in matches[:20])
                return f"Ambiguous: multiple files match '{path}':\n{listing}"
            return f"Error: No file called '{path}'."
        if os.path.isdir(resolved):
            return Desktop._list_dir(resolved)

        try:
            with open(resolved, "r", encoding="utf-8") as handle:
                text = handle.read()
        except UnicodeDecodeError:
            return f"'{resolved}' isn't a text file."
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
        return f"{resolved}:\n{page}{suffix}"

    @staticmethod
    def _list_dir(path: str) -> str:
        folder = os.path.expanduser(path)
        if not os.path.isdir(folder):
            return f"Error: '{path}' is not a folder."
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

    @method_job
    @capture_response
    def open(self, target: str) -> str:
        """
        [DESKTOP JOB] Opens something on this computer — an application by name
        ('notepad', 'chrome', 'spotify'), or a file or folder, which opens in whatever
        program normally handles it.
        Requires modules.desktop.allow_actions to be enabled in config.

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

        # Applications first: a bare "spotify" means the app, not a stray file
        # of that name. Resolve to a concrete executable BEFORE launching —
        # handing a bare name to ShellExecute pops a premature "cannot find"
        # dialog and reports failure even when the app opens moments later.
        exe = _resolve_executable(target)
        if exe is not None and os.path.splitext(exe)[1].lower() == ".exe":
            try:
                subprocess.Popen([exe])
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
        Requires modules.desktop.allow_actions to be enabled in config.
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
    def click_at(self, x: int, y: int) -> str:
        """
        [DESKTOP JOB] Clicks the mouse at the specified screen coordinates.
        Requires modules.desktop.allow_actions to be enabled in config.
        Use with caution — coordinates are absolute screen pixels.

        Args:
            x (int): Horizontal pixel coordinate. (required)
            y (int): Vertical pixel coordinate. (required)

        Returns:
            str: Confirmation of the click.
        """
        blocked = _require_actions("click_at")
        if blocked:
            return blocked

        import pyautogui

        try:
            pyautogui.click(int(x), int(y))
            return f"Clicked at ({x}, {y})."
        except Exception as e:
            return f"Error clicking at ({x}, {y}): {e}"

    @method_job(confirms=True)
    @capture_response
    def click_text(self, text: str, double: bool = False) -> str:
        """
        [DESKTOP JOB] Finds words on the screen and clicks them, so a button or a link
        can be pressed by name instead of by pixel coordinates.
        Requires modules.desktop.allow_actions to be enabled in config.

        Args:
            text (str): The words to click, as they appear on screen. (required)
            double (bool): Double-click instead of clicking once.

        Returns:
            str: What was clicked, or why nothing was.
        """
        blocked = _require_actions("click_text")
        if blocked:
            return blocked
        if not text:
            return "Error: What should I click?"

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
