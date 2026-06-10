import re
import typing
import uuid
from datetime import datetime

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement

_WEEKDAYS: typing.Dict[str, str] = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _scheduler_requirement() -> Requirement:
    return Requirement(
        pip_modules=["apscheduler", "dateparser"],
        setup_hint="pip install -r requirements/scheduler.txt",
    )


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
            return "cron", {"hour": 0, "minute": 0}, None

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
        for reminder_id, text, due_str in self._missed:
            self._fire_reminder(reminder_id, text, missed_at=due_str)

    # ------------------------------------------------------------------ jobs

    @capture_response
    @method_job
    def add_reminder(self, when: str, text: str) -> str:
        """
        [SCHEDULER JOB] Schedules a reminder or recurring notification for a future time.
        Reminders persist across restarts and fire via audio (if enabled) or print.

        Use this job when the user wants to:
        - Be reminded of something at a specific time ("remind me at 3pm to call mom")
        - Set a daily or recurring alarm ("every weekday at 9am say good morning")
        - Schedule a one-off future notification ("in 2 hours remind me to take a break")

        Examples for 'when': "in 30 minutes", "tomorrow at 9am", "at 3pm", "every day at 8am",
        "every weekday at 9am", "every Monday at 10am", "every 2 hours"

        Keywords: remind me, set reminder, schedule, notify, alarm, alert, every day, recurring,
                 in N minutes/hours, at H:MM, tomorrow at, next Monday

        Args:
            when (str): When to fire the reminder. Natural language accepted. (required)
            text (str): The reminder message to announce. (required)

        Returns:
            str: Confirmation with the scheduled time, or an error message.
        """
        if not when or not text:
            return "Error: Both 'when' and 'text' are required."

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
                display = run_date.strftime("%H:%M %d %b %Y")
                trigger_display = display
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
        }
        self._reminders[reminder_id] = meta
        try:
            from helpers.memory_db import save_reminder
            save_reminder(meta)
        except Exception as e:
            logger.log_error(str(e), "scheduler.add_reminder.db_save")
        return f"Reminder set: '{text}' — {trigger_display} (id: {reminder_id})"

    @capture_response
    @method_job
    def list_reminders(self) -> str:
        """
        [SCHEDULER JOB] Lists all active scheduled reminders.

        Use this job when the user wants to:
        - See all pending reminders
        - Check what reminders are scheduled
        - Review upcoming notifications

        Keywords: list reminders, show reminders, what reminders, active reminders, upcoming reminders

        Args:
            None

        Returns:
            str: All active reminders with their schedule, or a message if none.
        """
        jobs = self._sched.get_jobs()
        if not jobs:
            return "No reminders scheduled."

        lines = [f"{len(jobs)} active reminder(s):"]
        for job in jobs:
            meta = self._reminders.get(job.id, {})
            text = meta.get("text", job.id)
            when_str = meta.get("when_str", "")
            next_run = job.next_run_time
            next_str = next_run.strftime("%H:%M %d %b") if next_run else "recurring"
            lines.append(f"  [{job.id}] '{text}' — next: {next_str} ({when_str})")
        return "\n".join(lines)

    @capture_response
    @method_job
    def edit_reminder(self, id_or_text: str = "", new_when: str = "", new_text: str = "") -> str:
        """
        [SCHEDULER JOB] Edits an existing reminder — change its time, message, or both.

        Use this job when the user wants to:
        - Change when a reminder fires
        - Update the message of a scheduled reminder
        - Reschedule a reminder

        Keywords: edit reminder, update reminder, change reminder, reschedule reminder,
                 modify reminder, change reminder time, update reminder text

        Args:
            id_or_text (str): The reminder id (8-char code) or part of the reminder text. (required)
            new_when (str): New schedule (e.g. "tomorrow at 9am", "every day at 8am"). Optional.
            new_text (str): New reminder message. Optional.

        Returns:
            str: Confirmation with new schedule, or error if not found.
        """
        if not id_or_text:
            return "Error: Provide reminder id or text to identify it."
        if not new_when and not new_text:
            return "Error: Provide at least new_when or new_text."

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
                trigger_display = run_date.strftime("%H:%M %d %b %Y")
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
        }
        self._reminders[rid] = new_meta
        try:
            from helpers.memory_db import save_reminder
            save_reminder(new_meta)
        except Exception as e:
            logger.log_error(str(e), "scheduler.edit_reminder.db_save")

        return f"Reminder [{rid}] updated: '{text}' — {trigger_display}"

    @capture_response
    @method_job
    def cancel_reminder(self, id_or_text: str = "") -> str:
        """
        [SCHEDULER JOB] Cancels a scheduled reminder by id or partial text match.

        Use this job when the user wants to:
        - Cancel a reminder ("cancel the 3pm reminder")
        - Remove a scheduled notification
        - Stop a recurring reminder

        Keywords: cancel reminder, remove reminder, delete reminder, stop reminder, unschedule

        Args:
            id_or_text (str): The reminder id (8-char code) or part of the reminder text. (required)

        Returns:
            str: Confirmation of cancellation, or error if not found.
        """
        if not id_or_text:
            return "Error: Provide reminder id or text to cancel."

        to_cancel = []

        if id_or_text in self._reminders:
            to_cancel.append(id_or_text)
        else:
            needle = id_or_text.lower()
            for rid, meta in self._reminders.items():
                if needle in meta.get("text", "").lower() or needle in meta.get("when_str", "").lower():
                    to_cancel.append(rid)

        if not to_cancel:
            return f"No reminder found matching '{id_or_text}'."

        cancelled = []
        for rid in to_cancel:
            try:
                self._sched.remove_job(rid)
            except Exception:
                pass
            text = self._reminders.pop(rid, {}).get("text", rid)
            cancelled.append(f"'{text}'")
            try:
                from helpers.memory_db import delete_reminder
                delete_reminder(rid)
            except Exception:
                pass

        return f"Cancelled: {', '.join(cancelled)}."

    # ------------------------------------------------------------------ internal

    def _fire_reminder(self, reminder_id: str, text: str, missed_at: str = "") -> None:
        if missed_at:
            msg = f"Reminder (missed, was due {missed_at}): {text}"
        else:
            msg = f"Reminder: {text}"
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(msg)
        logger.log_system_event("reminder_fired", msg)
        meta = self._reminders.get(reminder_id, {})
        if missed_at or meta.get("trigger_type") == "date":
            self._reminders.pop(reminder_id, None)
            try:
                from helpers.memory_db import delete_reminder
                delete_reminder(reminder_id)
            except Exception:
                pass

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
                        self._missed.append((reminder_id, text, due_str))
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
