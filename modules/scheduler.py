import json
import re
import typing
import uuid
from datetime import datetime

from helpers.audio import Audio
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import ServiceRegistry, method_job, register_service
from helpers.requirements import Requirement

_WEEKDAYS: typing.Dict[str, str] = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _scheduler_requirement() -> Requirement:
    return Requirement(
        pip_modules=["apscheduler", "dateparser"],
        setup_hint="pip install -r requirements/core.txt",
    )


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def _label(meta: typing.Dict) -> str:
    """How to refer to a reminder when speaking or listing it."""
    text = meta.get("text", "")
    action = meta.get("action")
    if text and action:
        return f"'{text}' + run {action['job']}"
    if text:
        return f"'{text}'"
    if action:
        return f"run {action['job']}"
    return meta.get("id", "reminder")


def _describe(run_date: datetime) -> str:
    """A one-off 30 seconds out is a timer, not a clock time — "00:24 25 Aug" is
    a useless thing to say back for "turn the light on in 10 seconds"."""
    seconds = round((run_date - datetime.now()).total_seconds())
    if seconds < 60:
        return f"in {_plural(max(seconds, 1), 'second')}"
    if seconds < 3600:
        return f"in {_plural(round(seconds / 60), 'minute')}"
    if run_date.date() == datetime.now().date():
        return f"at {run_date.strftime('%H:%M')}"
    return run_date.strftime("%H:%M %d %b %Y")


def _parse_trigger(
    when_str: str,
) -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Dict], typing.Optional[str]]:
    """Return (trigger_type, kwargs, error). trigger_type in {'date','cron','interval'}."""
    lower = when_str.lower().strip()

    if "every" in lower:
        time_match = re.search(
            r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lower
        )
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

            cron_kw: typing.Dict[str, typing.Any] = {"hour": hour, "minute": minute}

            day_of_week = None
            for day_name, day_code in _WEEKDAYS.items():
                if day_name in lower:
                    day_of_week = day_code
                    break
            if "weekday" in lower:
                day_of_week = "mon-fri"
            elif "weekend" in lower:
                day_of_week = "sat,sun"

            if day_of_week:
                cron_kw["day_of_week"] = day_of_week

            return "cron", cron_kw, None

        interval_match = re.search(
            r"every\s+(\d+)\s+(minute|minutes|hour|hours)", lower
        )
        if interval_match:
            n = int(interval_match.group(1))
            unit = interval_match.group(2)
            if "hour" in unit:
                return "interval", {"hours": n}, None
            return "interval", {"minutes": n}, None

        if "day" in lower:
            return None, None, "Please specify a time for the daily reminder, e.g. 'every day at 8am'."

        return None, None, f"Could not parse recurring time: '{when_str}'"

    import dateparser
    dt = dateparser.parse(
        when_str,
        settings={"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DATES_FROM": "future"},
    )
    if dt is None:
        return None, None, f"Could not parse time: '{when_str}'"
    if dt < datetime.now():
        return None, None, f"'{when_str}' resolves to a past time ({dt.strftime('%H:%M %d %b')}). Please specify a future time."

    return "date", {"run_date": dt}, None


@register_service(
    module_name="scheduler",
    requires=_scheduler_requirement(),
)
class Scheduler:
    def __init__(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        self._sched = BackgroundScheduler(daemon=True)
        self._reminders: typing.Dict[str, typing.Dict] = {}
        self._missed: typing.List[typing.Tuple[str, str, str]] = []
        self._load_and_restore()
        self._sched.start()
        if self._missed:
            import threading
            missed = list(self._missed)
            def _fire_missed():
                import time
                time.sleep(2.0)
                for reminder_id, text, due_str in missed:
                    self._fire_reminder(reminder_id, text, missed_at=due_str)
            threading.Thread(target=_fire_missed, daemon=True, name="scheduler-missed").start()

    # ------------------------------------------------------------------ jobs

    @capture_response
    @method_job
    def add_reminder(self, when: str, text: str = "", action_job: str = "", action_args: typing.Optional[dict] = None) -> str:
        """
        [TIMER JOB] Sets a timer, alarm, reminder or recurring notification. This is the
        only timer in Wony — use it for every "in N seconds/minutes/hours", every alarm,
        and every "do X later" request. Timers survive restarts and fire out loud.

        A timer can announce a message, run another job, or both.

        Use this job when the user wants to:
        - Set a plain timer or alarm ("set a timer for 5 minutes", "wake me at 7am")
        - Be reminded of something ("remind me at 3pm to call mom", "in 2 hours remind me to stretch")
        - Run an action later ("turn the light on after 10 seconds", "play jazz in 1 hour",
          "in 30 minutes pause the music") — put the job in action_job and its arguments
          in action_args
        - Set a recurring alarm ("every weekday at 9am say good morning")

        Examples for 'when': "in 10 seconds", "in 30 minutes", "at 3pm", "tomorrow at 9am",
        "every day at 8am", "every weekday at 9am", "every Monday at 10am", "every 2 hours"

        Keywords: timer, set timer, countdown, alarm, set alarm, wake me, remind me,
                 set reminder, schedule, notify, alert, in N seconds/minutes/hours,
                 at H:MM, tomorrow at, every day, recurring, after N seconds, later,
                 then play, when the timer ends

        Args:
            when (str): When to fire. Natural language accepted. (required)
            text (str): Message to announce when it fires. Optional if action_job is set.
            action_job (str): Name of another job to run when it fires (e.g. "control_home_device",
                              "play_songs"). Use the job's exact registered name. Optional.
            action_args (dict): Keyword arguments for action_job, exactly as that job declares them
                                (e.g. {"target": "kitchen light", "action": "on"}). Optional.

        Returns:
            str: Confirmation with the scheduled time, or an error message.
        """
        if not when:
            return "Error: 'when' is required."
        if not text and not action_job:
            return "Error: Provide at least 'text' (message to announce) or 'action_job' (job to run)."

        # Normalize action_args: model may pass a JSON string
        if isinstance(action_args, str):
            try:
                action_args = json.loads(action_args)
            except Exception:
                action_args = {}
        if action_args is None:
            action_args = {}

        # Validate and resolve action_job
        action: typing.Optional[typing.Dict] = None
        if action_job:
            from helpers.agent import _resolve_job_name
            jobs = ServiceRegistry.get_all_jobs()
            resolved = _resolve_job_name(action_job, jobs)
            if resolved is None:
                return f"Error: Unknown action job '{action_job}'. Check available jobs with 'help'."
            action = {"job": resolved, "args": action_args}

        trigger_type, trigger_kw, error = _parse_trigger(when)
        if error:
            return f"Error: {error}"

        reminder_id = str(uuid.uuid4())[:8]

        def _fire(rid: str = reminder_id, msg: str = text) -> None:
            self._fire_reminder(rid, msg)

        try:
            if trigger_type == "date":
                run_date = trigger_kw["run_date"]
                self._sched.add_job(
                    _fire, "date", run_date=run_date, id=reminder_id, replace_existing=True
                )
                trigger_display = _describe(run_date)
                persist_kw = {"run_date": run_date.isoformat()}
            elif trigger_type == "cron":
                self._sched.add_job(
                    _fire, "cron", id=reminder_id, replace_existing=True, **trigger_kw
                )
                trigger_display = f"recurring ({when})"
                persist_kw = trigger_kw
            else:
                self._sched.add_job(
                    _fire, "interval", id=reminder_id, replace_existing=True, **trigger_kw
                )
                unit, n = next(iter(trigger_kw.items()))
                trigger_display = f"every {n} {unit}"
                persist_kw = trigger_kw
        except Exception as e:
            return f"Error scheduling reminder: {e}"

        meta = {
            "id": reminder_id,
            "text": text,
            "when_str": when,
            "trigger_type": trigger_type,
            "trigger_kwargs": {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in persist_kw.items()
            },
            "action": action,
        }
        self._reminders[reminder_id] = meta
        try:
            from helpers.memory_db import save_reminder
            save_reminder(meta)
        except Exception as e:
            logger.log_error(str(e), "scheduler.add_reminder.db_save")

        kind = "Timer" if trigger_type == "date" else "Reminder"
        return f"{kind} set: {_label(meta)} — {trigger_display} (id: {reminder_id})"

    @capture_response
    @method_job
    def list_reminders(self) -> str:
        """
        [TIMER JOB] Lists every running timer, alarm and reminder.

        Use this job when the user wants to:
        - See what timers are running ("how long left on my timer")
        - Check what reminders or alarms are scheduled

        Keywords: list timers, show timers, active timers, running timers, how long left,
                 list reminders, show reminders, what reminders, active alarms, upcoming

        Args:
            None

        Returns:
            str: All active timers with their schedule, or a message if none.
        """
        jobs = self._sched.get_jobs()
        if not jobs:
            return "Nothing scheduled."

        lines = [f"{len(jobs)} active:"]
        for job in jobs:
            meta = self._reminders.get(job.id, {"id": job.id})
            next_run = job.next_run_time
            # next_run_time is tz-aware; _describe compares against naive local now.
            next_str = _describe(next_run.replace(tzinfo=None)) if next_run else "recurring"
            # For a one-off, when_str is just a wordier form of next_str.
            recurrence = (
                f" ({meta['when_str']})"
                if meta.get("trigger_type") in ("cron", "interval") and meta.get("when_str")
                else ""
            )
            lines.append(f"  [{job.id}] {_label(meta)} — next: {next_str}{recurrence}")
        return "\n".join(lines)

    @capture_response
    @method_job
    def edit_reminder(self, id_or_text: str = "", new_when: str = "", new_text: str = "",
                      new_action_job: str = "", new_action_args: typing.Optional[dict] = None) -> str:
        """
        [TIMER JOB] Edits a timer, alarm or reminder — its time, message, action, or any combination.

        Use this job when the user wants to:
        - Change when a timer or alarm fires ("make it 10 minutes instead")
        - Update the message of a scheduled reminder
        - Change or add a job that runs when it fires

        Keywords: edit timer, change timer, make it, edit reminder, update reminder,
                 change reminder, reschedule, modify reminder, change alarm, change action

        Args:
            id_or_text (str): The reminder id (8-char code) or part of the reminder text. (required)
            new_when (str): New schedule (e.g. "tomorrow at 9am", "every day at 8am"). Optional.
            new_text (str): New reminder message. Optional.
            new_action_job (str): New job to run on fire (e.g. "play_songs"). Optional.
            new_action_args (dict): New kwargs for new_action_job. Optional.

        Returns:
            str: Confirmation with new schedule, or error if not found.
        """
        if not id_or_text:
            return "Error: Provide reminder id or text to identify it."
        if not new_when and not new_text and not new_action_job:
            return "Error: Provide at least new_when, new_text, or new_action_job."

        # Resolve the reminder
        rid = None
        if id_or_text in self._reminders:
            rid = id_or_text
        else:
            needle = id_or_text.lower()
            for r_id, meta in self._reminders.items():
                if needle in meta.get("text", "").lower() or needle in meta.get("when_str", "").lower():
                    rid = r_id
                    break

        if rid is None:
            return f"No reminder found matching '{id_or_text}'."

        meta = self._reminders[rid]
        text = new_text.strip() if new_text else meta.get("text", "")
        when_str = new_when.strip() if new_when else meta.get("when_str", "")

        # Resolve updated action
        if new_action_job:
            if isinstance(new_action_args, str):
                try:
                    new_action_args = json.loads(new_action_args)
                except Exception:
                    new_action_args = {}
            from helpers.agent import _resolve_job_name
            jobs = ServiceRegistry.get_all_jobs()
            resolved = _resolve_job_name(new_action_job, jobs)
            if resolved is None:
                return f"Error: Unknown action job '{new_action_job}'."
            action: typing.Optional[typing.Dict] = {"job": resolved, "args": new_action_args or {}}
        else:
            action = meta.get("action")

        if new_when:
            trigger_type, trigger_kw, error = _parse_trigger(new_when)
            if error:
                return f"Error: {error}"
        else:
            trigger_type = meta.get("trigger_type")
            trigger_kw = dict(meta.get("trigger_kwargs", {}))
            if trigger_type == "date" and "run_date" in trigger_kw:
                trigger_kw["run_date"] = datetime.fromisoformat(trigger_kw["run_date"])

        # Remove old job
        try:
            self._sched.remove_job(rid)
        except Exception:
            pass

        def _fire(r=rid, msg=text):
            self._fire_reminder(r, msg)

        try:
            if trigger_type == "date":
                run_date = trigger_kw["run_date"]
                self._sched.add_job(_fire, "date", run_date=run_date, id=rid, replace_existing=True)
                trigger_display = _describe(run_date)
                persist_kw = {"run_date": run_date.isoformat()}
            elif trigger_type == "cron":
                self._sched.add_job(_fire, "cron", id=rid, replace_existing=True, **trigger_kw)
                trigger_display = f"recurring ({when_str})"
                persist_kw = trigger_kw
            else:
                self._sched.add_job(_fire, "interval", id=rid, replace_existing=True, **trigger_kw)
                unit, n = next(iter(trigger_kw.items()))
                trigger_display = f"every {n} {unit}"
                persist_kw = trigger_kw
        except Exception as e:
            return f"Error rescheduling reminder: {e}"

        new_meta = {
            "id": rid,
            "text": text,
            "when_str": when_str,
            "trigger_type": trigger_type,
            "trigger_kwargs": {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in persist_kw.items()
            },
            "action": action,
        }
        self._reminders[rid] = new_meta
        try:
            from helpers.memory_db import save_reminder
            save_reminder(new_meta)
        except Exception as e:
            logger.log_error(str(e), "scheduler.edit_reminder.db_save")

        return f"[{rid}] updated: {_label(new_meta)} — {trigger_display}"

    @capture_response
    @method_job
    def cancel_reminder(self, id_or_text: str = "") -> str:
        """
        [TIMER JOB] Cancels a timer, alarm or reminder by id, partial text, or all at once.

        Use this job when the user wants to:
        - Cancel a timer ("cancel the timer", "stop the 3pm reminder")
        - Cancel everything scheduled ("cancel all timers")
        - Stop a recurring alarm

        Keywords: cancel timer, stop timer, cancel all timers, clear timers, cancel alarm,
                 cancel reminder, remove reminder, delete reminder, stop reminder, unschedule

        Args:
            id_or_text (str): The id (8-char code), part of the text, or "all" to cancel
                              everything. (required)

        Returns:
            str: Confirmation of cancellation, or error if not found.
        """
        if not id_or_text:
            return "Error: Provide an id, some of the text, or 'all'."

        needle = id_or_text.lower().strip()
        if needle in ("all", "everything", "all timers", "all reminders"):
            to_cancel = list(self._reminders)
        elif id_or_text in self._reminders:
            to_cancel = [id_or_text]
        else:
            to_cancel = [
                rid for rid, meta in self._reminders.items()
                if needle in meta.get("text", "").lower()
                or needle in meta.get("when_str", "").lower()
                or needle in (meta.get("action") or {}).get("job", "").lower()
            ]

        if not to_cancel:
            return f"Nothing scheduled matching '{id_or_text}'."

        cancelled = []
        for rid in to_cancel:
            try:
                self._sched.remove_job(rid)
            except Exception:
                pass
            cancelled.append(_label(self._reminders.pop(rid, {"id": rid})))
            try:
                from helpers.memory_db import delete_reminder
                delete_reminder(rid)
            except Exception:
                pass

        return f"Cancelled: {', '.join(cancelled)}."

    # ------------------------------------------------------------------ internal

    def _fire_reminder(self, reminder_id: str, text: str, missed_at: str = "") -> None:
        meta = self._reminders.get(reminder_id, {})
        action = meta.get("action")
        if missed_at:
            # text here is already a _label() built at restore time.
            msg = f"Reminder (missed, was due {missed_at}): {text}"
            Audio.notify(msg)
            logger.log_system_event("reminder_fired_missed", msg)
        else:
            if text:
                msg = f"Reminder: {text}"
                Audio.notify(msg)
                logger.log_system_event("reminder_fired", msg)
            if action:
                self._run_action(action)
        if missed_at or meta.get("trigger_type") == "date":
            self._reminders.pop(reminder_id, None)
            try:
                from helpers.memory_db import delete_reminder
                delete_reminder(reminder_id)
            except Exception:
                pass

    def _run_action(self, action: typing.Dict) -> None:
        from helpers.agent import _resolve_job_name
        from helpers.decorators import agent_lock

        jobs = ServiceRegistry.get_all_jobs()
        resolved = _resolve_job_name(action.get("job", ""), jobs)
        if resolved is None:
            err = f"unknown job '{action.get('job')}'"
            logger.log_error(err, "scheduler.run_action")
            Audio.notify(f"Could not run scheduled action: {err}.")
            return
        # A timer firing mid-turn would otherwise write into the running agent's
        # tool-outcome ledger and be silenced by its _agent_active suppression.
        # Waiting for the turn to end costs a few seconds and keeps both honest.
        with agent_lock:
            try:
                jobs[resolved](**(action.get("args") or {}))
            except Exception as e:
                logger.log_error(str(e), f"scheduler.run_action.{resolved}")
                Audio.notify(f"Scheduled action failed: {e}")

    def _load_and_restore(self) -> None:
        try:
            from helpers.memory_db import all_reminders, delete_reminder
            stored = all_reminders()
        except Exception:
            return

        now = datetime.now()
        for meta in stored:
            reminder_id = meta["id"]
            trigger_type = meta.get("trigger_type")
            trigger_kw = dict(meta.get("trigger_kwargs", {}))
            text = meta.get("text", "")

            def _make_fire(rid: str = reminder_id, msg: str = text):
                def _fire():
                    self._fire_reminder(rid, msg)
                return _fire

            try:
                if trigger_type == "date":
                    run_date = datetime.fromisoformat(trigger_kw["run_date"])
                    if run_date <= now:
                        due_str = run_date.strftime("%H:%M %d %b")
                        self._missed.append((reminder_id, _label(meta), due_str))
                        delete_reminder(reminder_id)
                        continue
                    self._sched.add_job(
                        _make_fire(), "date", run_date=run_date,
                        id=reminder_id, replace_existing=True,
                    )
                elif trigger_type == "cron":
                    self._sched.add_job(
                        _make_fire(), "cron", id=reminder_id,
                        replace_existing=True, **trigger_kw,
                    )
                elif trigger_type == "interval":
                    kw = {k: int(v) for k, v in trigger_kw.items()}
                    self._sched.add_job(
                        _make_fire(), "interval", id=reminder_id,
                        replace_existing=True, **kw,
                    )
                else:
                    continue
                self._reminders[reminder_id] = meta
            except Exception as e:
                logger.log_error(str(e), f"scheduler.restore_reminder.{reminder_id}")
