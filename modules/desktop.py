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
            "Set modules.desktop.allow_actions: true in config.yaml to enable "
            "type/click/clipboard-write/file-open operations."
        )
    return None


_SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".git", ".venv"}


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

    @method_job
    @capture_response
    def list_windows(self) -> str:
        """
        [DESKTOP JOB] Lists all currently open application windows on the desktop.

        Use this job when the user wants to:
        - See what windows/apps are open
        - Find which app to focus
        - List running windows

        Keywords: list windows, show windows, open windows, what's open, running apps,
                 what apps are open

        Args:
            None

        Returns:
            str: Names of all visible windows.
        """
        import pygetwindow as gw

        windows = [w.title for w in gw.getAllWindows() if w.title.strip()]
        if not windows:
            return "No visible windows found."
        return "Open windows:\n" + "\n".join(f"  - {w}" for w in sorted(set(windows)))

    @method_job
    @capture_response
    def get_clipboard(self) -> str:
        """
        [DESKTOP JOB] Reads and returns the current clipboard content.

        Use this job when the user wants to:
        - See what's in the clipboard
        - Read copied text
        - Get clipboard contents

        Keywords: clipboard, what's in clipboard, read clipboard, paste, copied text,
                 get clipboard

        Args:
            None

        Returns:
            str: Current clipboard text content.
        """
        import pyperclip

        text = pyperclip.paste()
        if not text:
            return "Clipboard is empty."
        preview = text[:500]
        suffix = f"\n[… {len(text) - 500} more chars]" if len(text) > 500 else ""
        return f"Clipboard content:\n{preview}{suffix}"

    @method_job
    @capture_response
    def find_file(self, name: str, search_path: str = "") -> str:
        """
        [DESKTOP JOB] Searches for files matching a name or pattern on the filesystem.
        Searches from the user's home directory by default, or a configured/specified path.

        Use this job when the user wants to:
        - Find a file by name
        - Locate a document or folder
        - Search for files matching a pattern

        Keywords: find file, search file, where is, locate file, look for file, find document

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

    # ------------------------------------------------------------------ action-gated

    @method_job
    @capture_response
    def focus_window(self, title: str) -> str:
        """
        [DESKTOP JOB] Brings a window to the foreground and gives it focus.
        Matches by partial title (case-insensitive).

        Use this job when the user wants to:
        - Switch to an application window
        - Bring a window to the front
        - Focus a specific app

        Keywords: focus, switch to, bring to front, activate window, open app window

        Args:
            title (str): Partial window title to match (case-insensitive). (required)

        Returns:
            str: Confirmation or error message.
        """
        import pygetwindow as gw

        needle = title.lower()
        windows = [w for w in gw.getAllWindows() if needle in w.title.lower()]
        if not windows:
            return f"No window found matching '{title}'."

        target = windows[0]
        try:
            if getattr(target, "isMinimized", False):
                target.restore()
            target.activate()
            return f"Focused window: '{target.title}'."
        except Exception:
            # pygetwindow.activate() throws intermittently on Windows; the
            # minimize→restore toggle reliably forces the window forward.
            try:
                target.minimize()
                target.restore()
                return f"Focused window: '{target.title}'."
            except Exception as e:
                return f"Could not focus '{target.title}': {e}"

    @method_job
    @capture_response
    def open_app(self, name: str) -> str:
        """
        [DESKTOP JOB] Opens an application by name using the Windows shell.
        Works for app names known to Windows (e.g. 'notepad', 'chrome', 'spotify', 'calculator').
        Requires modules.desktop.allow_actions to be enabled in config.

        Use this job when the user wants to:
        - Open an application
        - Launch a program
        - Start an app

        Keywords: open, launch, start, run app, open program, open application, start app

        Args:
            name (str): Application name or executable path to open. (required)

        Returns:
            str: Confirmation or error.
        """
        blocked = _require_actions("open_app")
        if blocked:
            return blocked

        if not name:
            return "Error: No application name provided."

        # Resolve to a concrete executable BEFORE launching. Handing a bare
        # name to ShellExecute/start pops a premature "cannot find" dialog and
        # reports failure even when the app opens moments later. Resolving up
        # front means a single, final success/error.
        exe = _resolve_executable(name)
        if exe is None:
            return (
                f"Error: Could not find an application named '{name}'. "
                "Provide the full path to its .exe, or check the name."
            )

        try:
            subprocess.Popen([exe])
            return f"Opening '{name}'."
        except Exception as e:
            return f"Error opening '{name}': {e}"

    @method_job
    @capture_response
    def open_file(self, path: str) -> str:
        """
        [DESKTOP JOB] Opens a file with its default application (like double-clicking it).
        Requires modules.desktop.allow_actions to be enabled in config.

        Use this job when the user wants to:
        - Open a specific file
        - View a document or image
        - Open a file with its default program

        Keywords: open file, view file, open document, open image, open with

        Args:
            path (str): Full path OR just a filename (with or without extension).
                Bare names are resolved against Desktop, Documents, Downloads,
                home, and the current directory (incl. OneDrive-redirected
                folders). (required)

        Returns:
            str: Confirmation or error.
        """
        blocked = _require_actions("open_file")
        if blocked:
            return blocked

        if not path:
            return "Error: No file path provided."

        resolved, matches = _resolve_file(path)
        if resolved is None:
            if matches:
                listing = "\n".join(f"  {m}" for m in matches[:20])
                return (
                    f"Ambiguous: multiple files match '{path}'. "
                    f"Specify a full path:\n{listing}"
                )
            return (
                f"Error: File not found: '{path}'. "
                f"Searched: {', '.join(_known_dirs())}"
            )

        try:
            os.startfile(resolved)
            return f"Opened: {resolved}"
        except Exception as e:
            return f"Error opening file: {e}"

    @method_job
    @capture_response
    def set_clipboard(self, text: str) -> str:
        """
        [DESKTOP JOB] Sets the clipboard to the given text.
        Requires modules.desktop.allow_actions to be enabled in config.

        Use this job when the user wants to:
        - Copy text to clipboard
        - Set clipboard content
        - Prepare text for pasting

        Keywords: copy to clipboard, set clipboard, put in clipboard, clipboard copy

        Args:
            text (str): Text to place in the clipboard. (required)

        Returns:
            str: Confirmation.
        """
        blocked = _require_actions("set_clipboard")
        if blocked:
            return blocked

        import pyperclip

        pyperclip.copy(text)
        preview = text[:80] + ("…" if len(text) > 80 else "")
        return f"Copied to clipboard: '{preview}'"

    @method_job
    @capture_response
    def type_text(self, text: str) -> str:
        """
        [DESKTOP JOB] Types text into the currently focused application as keyboard input.
        Requires modules.desktop.allow_actions to be enabled in config.
        Note: works best with ASCII text; unicode characters are handled via clipboard paste.

        Use this job when the user wants to:
        - Type text into the active window
        - Input text automatically
        - Autofill a field

        Keywords: type, input text, write in, type into, keyboard input, autotype

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
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception as e:
            return f"Error typing text: {e}"

        preview = text[:60] + ("…" if len(text) > 60 else "")
        return f"Typed: '{preview}'"

    @method_job
    @capture_response
    def click_at(self, x: int, y: int) -> str:
        """
        [DESKTOP JOB] Clicks the mouse at the specified screen coordinates.
        Requires modules.desktop.allow_actions to be enabled in config.
        Use with caution — coordinates are absolute screen pixels.

        Use this job when the user wants to:
        - Click a specific position on screen
        - Interact with a UI element at known coordinates
        - Automate a click action

        Keywords: click, click at, mouse click, press, tap coordinates

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
