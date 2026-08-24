import threading
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
        pass_stop_event: bool = False,
    ) -> bool:
        """
        Start a named background job.

        If interval is given the target is called repeatedly with that delay between calls.
        If interval is None the target is called once (but runs in a daemon thread).
        If pass_stop_event is True, target is called with the job's stop_event as its
        only argument — use this for jobs that sleep for a long time (e.g. timers) so
        stop_all()/stop() can wake and cancel them instead of leaving them asleep
        until the delay elapses on its own.
        Returns False if a job with that name is already running.
        """
        with cls._lock:
            if name in cls._jobs and cls._jobs[name]["thread"].is_alive():
                return False

            stop_event = threading.Event()

            def _call() -> None:
                if pass_stop_event:
                    target(stop_event)
                else:
                    target()

            def _report_failure(e: Exception, announce: bool) -> None:
                from helpers.logger import logger
                logger.log_error(str(e), context=f"job:{name}")
                # File-only logging is invisible to the user — a background
                # job dying silently leaves them assuming it's still running.
                print(f"[job:{name}] failed: {e}")
                if not announce:
                    return
                try:
                    from helpers.audio import Audio
                    Audio.notify(f"Background job {name} failed: {e}")
                except Exception:
                    pass

            if interval is not None:
                def _loop():
                    announced = False
                    while not stop_event.wait(interval):
                        try:
                            _call()
                        except Exception as e:
                            # Only speak the first failure of a recurring job —
                            # a broken poller ticking every few seconds would
                            # otherwise nag on every retry.
                            _report_failure(e, announce=not announced)
                            announced = True
                thread_target = _loop
            else:
                def _once():
                    try:
                        _call()
                    except Exception as e:
                        _report_failure(e, announce=True)
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
