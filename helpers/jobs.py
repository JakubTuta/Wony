import threading
import typing


class BackgroundJobs:
    """Centralized registry for daemon background threads with cooperative stop."""

    _jobs: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    # Specs of jobs stopped by suspend_all(), so resume_suspended() can bring
    # them back. Pausing the assistant used to call stop_all(), which silently
    # ended every poller the user had asked for ("check my email every 15 min")
    # with no way to get them back short of restarting the app.
    _suspended: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
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
                    from helpers.notify import notify
                    notify(f"Background job {name} failed: {e}", kind="error", source="jobs")
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
            cls._jobs[name] = {
                "thread": thread,
                "stop_event": stop_event,
                "spec": {
                    "target": target,
                    "interval": interval,
                    "pass_stop_event": pass_stop_event,
                },
            }
            cls._suspended.pop(name, None)
            thread.start()
            return True

    @classmethod
    def stop(cls, name: str) -> bool:
        """Signal a named job to stop. Returns False if not found."""
        with cls._lock:
            job = cls._jobs.get(name)
            cls._suspended.pop(name, None)
            if job is None:
                return False
            job["stop_event"].set()
            cls._jobs.pop(name, None)
            return True

    @classmethod
    def stop_all(cls) -> typing.List[str]:
        """Stop all running jobs for good. Returns list of stopped job names."""
        with cls._lock:
            names = list(cls._jobs.keys())
            for job in cls._jobs.values():
                job["stop_event"].set()
            cls._jobs.clear()
            cls._suspended.clear()
        return names

    @classmethod
    def suspend_all(cls) -> typing.List[str]:
        """Stop every running job but remember how to start it again.

        Used when the assistant is paused — a paused assistant should not be
        announcing new email, but resuming should give the user back the
        pollers they asked for rather than silently dropping them.
        """
        with cls._lock:
            names = list(cls._jobs.keys())
            for name, job in cls._jobs.items():
                job["stop_event"].set()
                cls._suspended[name] = job["spec"]
            cls._jobs.clear()
        return names

    @classmethod
    def resume_suspended(cls) -> typing.List[str]:
        """Restart everything suspend_all() stopped. Returns restarted names."""
        with cls._lock:
            pending = dict(cls._suspended)
            cls._suspended.clear()
        restarted = []
        for name, spec in pending.items():
            if cls.start(
                name,
                spec["target"],
                interval=spec["interval"],
                pass_stop_event=spec["pass_stop_event"],
            ):
                restarted.append(name)
        return restarted

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
