"""Finding the Wayland session from a process that was not started inside it."""
import os
import typing


def session_env() -> typing.Optional[typing.Dict[str, str]]:
    """Environment for a Wayland client, or None if there is no session.

    Wony runs under `systemctl --user`, which is the same user as the desktop
    session but not the same environment: systemd hands a service neither
    WAYLAND_DISPLAY nor XDG_RUNTIME_DIR. Both are recoverable — the runtime dir
    from the uid, the display from whichever socket is sitting in it (labwc
    tends to be wayland-0, wayfire wayland-1, so guessing either would be wrong
    half the time).
    """
    env = dict(os.environ)

    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime or not os.path.isdir(runtime):
        getuid = getattr(os, "getuid", None)
        if getuid is None:
            return None
        runtime = f"/run/user/{getuid()}"
        if not os.path.isdir(runtime):
            return None
        env["XDG_RUNTIME_DIR"] = runtime

    if not env.get("WAYLAND_DISPLAY"):
        sockets = sorted(
            name
            for name in os.listdir(runtime)
            if name.startswith("wayland-") and not name.endswith(".lock")
        )
        if not sockets:
            return None
        env["WAYLAND_DISPLAY"] = sockets[0]

    return env
