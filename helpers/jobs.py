import threading
import time
import typing


class BackgroundJobs:
    """Centralized registry for daemon background threads with cooperative stop."""

    _jobs: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    _lock = threading.Lock()

    @classmethod
    def start(
        cls,
        name: str,
        target: typing.Callable,
        interval: typing.Optional[float] = None,
    ) -> bool:
        """
        Start a named background job.

        If interval is given the target is called repeatedly with that delay between calls.
        If interval is None the target is called once (but runs in a daemon thread).
        Returns False if a job with that name is already running.
        """
        with cls._lock:
            if name in cls._jobs and cls._jobs[name]["thread"].is_alive():
                return False

            stop_event = threading.Event()

            if interval is not None:
                def _loop():
                    while not stop_event.wait(interval):
                        try:
                            target()
                        except Exception as e:
                            print(f"[{name}] error: {e}")
                thread_target = _loop
            else:
                def _once():
                    try:
                        target()
                    except Exception as e:
                        print(f"[{name}] error: {e}")
                thread_target = _once

            thread = threading.Thread(target=thread_target, name=name, daemon=True)
            cls._jobs[name] = {"thread": thread, "stop_event": stop_event}
            thread.start()
            return True

    @classmethod
    def stop(cls, name: str) -> bool:
        """Signal a named job to stop. Returns False if not found."""
        with cls._lock:
            job = cls._jobs.get(name)
            if job is None:
                return False
            job["stop_event"].set()
            cls._jobs.pop(name, None)
            return True

    @classmethod
    def stop_all(cls) -> typing.List[str]:
        """Stop all running jobs. Returns list of stopped job names."""
        with cls._lock:
            names = list(cls._jobs.keys())
            for job in cls._jobs.values():
                job["stop_event"].set()
            cls._jobs.clear()
        return names

    @classmethod
    def list_jobs(cls) -> typing.List[str]:
        """Return names of currently running background jobs."""
        with cls._lock:
            return [name for name, job in cls._jobs.items() if job["thread"].is_alive()]

    @classmethod
    def is_running(cls, name: str) -> bool:
        with cls._lock:
            job = cls._jobs.get(name)
            return job is not None and job["thread"].is_alive()
