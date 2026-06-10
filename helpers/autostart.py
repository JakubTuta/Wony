"""
Windows autostart via Task Scheduler.

Installs/removes a logon task that runs:
  <venv>/Scripts/pythonw.exe <repo>/wony.py tray

Uses schtasks.exe (no pywin32 required). For restart-on-crash and hidden
window, generates an XML task definition (requires no extra tools beyond
what's in Windows).

Usage:
  python wony.py autostart install
  python wony.py autostart uninstall
"""
import os
import subprocess
import sys
import tempfile
import textwrap


TASK_NAME = "WonyAssistant"


def _pythonw() -> str:
    """Resolve pythonw.exe, preferring the repo venv over the global interpreter.

    Order:
      1. <repo>/venv/Scripts/pythonw.exe
      2. <repo>/.venv/Scripts/pythonw.exe
      3. $VIRTUAL_ENV/Scripts/pythonw.exe
      4. sys.executable directory (current interpreter)
    """
    repo_root = os.path.dirname(_wony_script())
    venv_candidates = [
        os.path.join(repo_root, "venv", "Scripts", "pythonw.exe"),
        os.path.join(repo_root, ".venv", "Scripts", "pythonw.exe"),
    ]
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
        venv_candidates.append(os.path.join(virtual_env, "Scripts", "pythonw.exe"))

    for c in venv_candidates:
        if os.path.isfile(c):
            return c

    # Fall back to interpreter-adjacent pythonw.exe
    exe = sys.executable
    base = os.path.dirname(exe)
    for c in [
        os.path.join(base, "pythonw.exe"),
        os.path.join(base, "Scripts", "pythonw.exe"),
    ]:
        if os.path.isfile(c):
            return c
    return exe.replace("python.exe", "pythonw.exe")


def _check_deps(pythonw: str) -> None:
    """Warn if the chosen interpreter is missing required packages."""
    python_exe = os.path.join(os.path.dirname(pythonw), "python.exe")
    if not os.path.isfile(python_exe):
        python_exe = pythonw  # best-effort
    try:
        result = subprocess.run(
            [python_exe, "-c", "import pystray, PIL, fastapi, uvicorn"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            missing = result.stderr.strip().split("'")
            pkg = missing[1] if len(missing) > 1 else "unknown"
            print(f"[autostart] WARNING: '{python_exe}' is missing package '{pkg}'.")
            print(f"[autostart] Run: \"{python_exe}\" -m pip install -r requirements/tray.txt")
            print("[autostart] Task was installed but will crash at login.")
    except Exception:
        pass  # non-fatal — we still install the task


def _wony_script() -> str:
    """Absolute path to wony.py."""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "wony.py")
    )


def _run_schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
    )


def install() -> None:
    """Install a Windows logon Task Scheduler entry for Wony tray."""
    pythonw = _pythonw()
    wony = _wony_script()

    if not os.path.isfile(pythonw):
        print(f"[autostart] Warning: pythonw.exe not found at {pythonw}")
        print("[autostart] The task will be created but may not run silently.")
    else:
        _check_deps(pythonw)

    username = os.environ.get("USERNAME", "")

    # Build XML for full features: hidden, restart-on-crash
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers>
            <LogonTrigger>
              <Enabled>true</Enabled>
              <UserId>{username}</UserId>
            </LogonTrigger>
          </Triggers>
          <Principals>
            <Principal id="Author">
              <UserId>{username}</UserId>
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>LeastPrivilege</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <Hidden>true</Hidden>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <RestartOnFailure>
              <Interval>PT1M</Interval>
              <Count>3</Count>
            </RestartOnFailure>
            <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{pythonw}</Command>
              <Arguments>"{wony}" tray</Arguments>
              <WorkingDirectory>{os.path.dirname(wony)}</WorkingDirectory>
            </Exec>
          </Actions>
        </Task>
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-16"
    ) as f:
        f.write(xml)
        xml_path = f.name

    try:
        result = _run_schtasks(
            "/Create", "/XML", xml_path, "/TN", TASK_NAME, "/F"
        )
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass

    if result.returncode == 0:
        print(f"[autostart] Task '{TASK_NAME}' installed.")
        print(f"  Interpreter:   {pythonw}")
        print(f"  Runs at logon: {pythonw} \"{wony}\" tray")
        print("  Wony will start automatically and silently on next login.")
        print("  Tip: if this interpreter changed, run 'autostart uninstall' then 'autostart install' again.")
    else:
        print(f"[autostart] Failed to install task (exit {result.returncode}):")
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        print()
        print("[autostart] Fallback: run this command manually as Administrator:")
        print(
            f'  schtasks /Create /TN {TASK_NAME} /SC ONLOGON '
            f'/TR "\\"{pythonw}\\" \\"{wony}\\" tray" /F'
        )


def uninstall() -> None:
    """Remove the Wony autostart task."""
    result = _run_schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if result.returncode == 0:
        print(f"[autostart] Task '{TASK_NAME}' removed.")
    else:
        out = (result.stdout + result.stderr).strip()
        if "cannot find" in out.lower() or "does not exist" in out.lower():
            print(f"[autostart] Task '{TASK_NAME}' not found (already removed or never installed).")
        else:
            print(f"[autostart] Failed to remove task (exit {result.returncode}):")
            print(out)


def status() -> None:
    """Print current task status."""
    result = _run_schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST")
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print(f"Task '{TASK_NAME}' not found.")
