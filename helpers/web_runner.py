"""
WebServerController: runs a uvicorn.Server in a daemon thread.

Using uvicorn.Server directly (not uvicorn.run) so it can be started from a
background thread. The signal-handler install must be disabled because
signal.signal() raises ValueError when called from a non-main thread.
"""
import threading
import typing


class WebServerController:
    def __init__(self, app: typing.Any, host: str, port: int) -> None:
        import uvicorn
        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server: typing.Optional[typing.Any] = None
        self._thread: typing.Optional[threading.Thread] = None

    def _make_server(self) -> typing.Any:
        import uvicorn
        server = uvicorn.Server(self._config)
        # Disable uvicorn's own signal-handler install; we are not on the main thread.
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        return server

    def start(self) -> bool:
        """Start the server thread. Returns False if already running."""
        if self._thread is not None and self._thread.is_alive():
            return False
        # Always create a fresh Server instance — uvicorn.Server cannot be reused
        # after stop() because internal lifecycle state (started, etc.) is not reset.
        self._server = self._make_server()
        self._thread = threading.Thread(
            target=self._server.run,
            name="webserver",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the server to shut down and wait for the thread to exit."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        return f"http://{self._config.host}:{self._config.port}"
