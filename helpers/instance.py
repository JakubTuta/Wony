"""One running Wony per checkout.

Two copies would each restore every timer and reminder from wony.db and fire it,
poll the same mailbox, and race for the same files. So whatever starts the
assistant claims this first.

An OS file lock, not a bound port or a named mutex: the OS drops it when Wony
dies however it dies, it belongs to this folder (a second checkout is a
different Wony), and an unrelated program can never look like a running one.
"""
import os
import sys
import typing

from helpers.paths import repo_path

_LOCK_FILE = repo_path(".wony_lock")

# The file is "#" (the byte that gets locked) followed by the owner's pid, padded
# to a fixed width so it never needs truncating. Readers start after the "#":
# on Windows the locked byte cannot be read by anyone else.
_PID_WIDTH = 12

_fd: typing.Optional[int] = None


def _lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def acquire() -> bool:
    """True if this process is now the only Wony, False if another one is."""
    global _fd
    if _fd is not None:
        return True

    fd = os.open(_LOCK_FILE, os.O_RDWR | os.O_CREAT)
    if not _lock(fd):
        os.close(fd)
        return False

    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"#{os.getpid():<{_PID_WIDTH}}".encode("ascii"))
    _fd = fd
    return True


def release() -> None:
    """Give the claim up now rather than at exit. Restart needs this: the new
    process must not lose the race against this one still shutting down."""
    global _fd
    if _fd is not None:
        os.close(_fd)
        _fd = None


def holder_pid() -> typing.Optional[int]:
    """The pid of the Wony that holds the claim, if it can be read."""
    try:
        with open(_LOCK_FILE, "rb") as handle:
            handle.seek(1)
            return int(handle.read(_PID_WIDTH).decode("ascii").strip())
    except (OSError, ValueError):
        return None


def claim_or_exit(stop_hint: str) -> None:
    """For the entry points that print to a console: claim, or say why not and
    exit. `stop_hint` is how to stop the running copy on this machine."""
    if acquire():
        return
    pid = holder_pid()
    running = f"Wony is already running (process {pid})." if pid else "Wony is already running."
    print(
        f"\n{running} Only one copy can run at a time, because a second would repeat\n"
        f"every timer and reminder. {stop_hint}\n"
    )
    sys.exit(1)
