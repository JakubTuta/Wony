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

        root = search_path or Config.get("modules.desktop.file_search_root", "~")
        root = os.path.expanduser(root)

        if not os.path.isdir(root):
            return f"Error: Search path '{root}' does not exist."

        needle = name.lower()
        matches: typing.List[str] = []
        max_results = 20

        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".git")
                ]
                for fname in filenames:
                    if needle in fname.lower():
                        matches.append(os.path.join(dirpath, fname))
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
        except PermissionError:
            pass

        if not matches:
            return f"No files found matching '{name}' under {root}."

        suffix = f"\n(Showing first {max_results}; there may be more.)" if len(matches) == max_results else ""
        return f"Found {len(matches)} file(s) matching '{name}':\n" + "\n".join(f"  {p}" for p in matches) + suffix

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
            target.activate()
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

        try:
            os.startfile(name)
            return f"Opening '{name}'."
        except OSError:
            try:
                subprocess.run(["cmd", "/c", "start", "", name], check=False)
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
            path (str): Full path to the file to open. (required)

        Returns:
            str: Confirmation or error.
        """
        blocked = _require_actions("open_file")
        if blocked:
            return blocked

        if not path:
            return "Error: No file path provided."
        if not os.path.exists(path):
            return f"Error: File not found: '{path}'"

        try:
            os.startfile(path)
            return f"Opened: {path}"
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
