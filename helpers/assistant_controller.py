"""
AssistantController: owns the runtime state of the always-on tray process.

Manages the Employer brain, the in-process web server, and the wake-word
listener. Start/Stop control listening + web server together.
"""
import threading
import typing

from helpers.web_runner import WebServerController


class AssistantController:
    def __init__(
        self,
        employer: typing.Any,
        web: WebServerController,
        wakeword: typing.Optional[typing.Any] = None,
    ) -> None:
        self._employer = employer
        self._web = web
        self._wakeword = wakeword
        self._state = "stopped"
        self._lock = threading.Lock()

    # ── Public interface ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start web server + wake-word listener (idempotent)."""
        with self._lock:
            self._web.start()
            if self._wakeword is not None:
                self._wakeword.start()
            self._state = "running"

    def stop(self) -> None:
        """Stop everything: wake word + web server + background jobs (idempotent)."""
        with self._lock:
            if self._wakeword is not None:
                self._wakeword.stop()
            try:
                from helpers.jobs import BackgroundJobs
                BackgroundJobs.stop_all()
            except Exception:
                pass
            self._web.stop()
            self._state = "stopped"

    def shutdown(self) -> None:
        """Full teardown: stop everything then run bootstrap.shutdown()."""
        self.stop()
        try:
            from helpers.bootstrap import shutdown as _bootstrap_shutdown
            _bootstrap_shutdown()
        except Exception:
            pass

    def ensure_web(self) -> None:
        """Ensure the web server is running (start it if stopped)."""
        if not self._web.is_running():
            self._web.start()

    def is_running(self) -> bool:
        return self._state == "running"

    @property
    def web_url(self) -> str:
        return self._web.url

    @property
    def employer(self) -> typing.Any:
        return self._employer
