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
    """Resolve pythonw.exe from the current Python executable."""
    exe = sys.executable
    base = os.path.dirname(exe)
    candidates = [
        os.path.join(base, "pythonw.exe"),
        os.path.join(base, "Scripts", "pythonw.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # Fallback: replace python.exe with pythonw.exe in-place
    return exe.replace("python.exe", "pythonw.exe")


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
        print(f"  Runs at logon: {pythonw} \"{wony}\" tray")
        print("  Wony will start automatically and silently on next login.")
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
