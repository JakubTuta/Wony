import os
import typing
from datetime import datetime, timedelta

from helpers.accounts import CREDENTIALS_FILE, GoogleAccounts
from helpers.notify import notify
from helpers.cache import Cache
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement
from helpers.timeutil import local_tz, now_local

_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Tuning knobs, not settings — nobody asking "what's on today" should have to
# pick a result cap or a search window, and the right values don't vary by user.
# Events returned when the caller doesn't cap it.
_DEFAULT_MAX_RESULTS = 10
# How far ahead "what's coming up" looks by default.
_DEFAULT_LOOKAHEAD_HOURS = 24
# Window a keyword search covers when no dates are given.
_SEARCH_DAYS_BACK = 30
_SEARCH_DAYS_AHEAD = 90
# How often "watch my calendar" polls when no interval is given.
_DEFAULT_POLL_INTERVAL_MINUTES = 15


def _calendar_job_name(account_name: str) -> str:
    return f"calendar_polling_{account_name}"


@register_service(
    module_name="calendar",
    requires=Requirement(
        files=[CREDENTIALS_FILE],
        pip_modules=["googleapiclient", "google_auth_oauthlib", "google.auth"],
        setup_hint=(
            "Create an OAuth client (Desktop) in Google Cloud Console with Calendar API "
            "and Gmail API enabled, download it to credentials/google_credentials.json, "
            "then run: pip install -r requirements/calendar.txt"
        ),
    ),
)
class Calendar:
    """Google Calendar service for reading and managing events. Supports multiple Google accounts."""

    def __init__(self):
        self._services: typing.Dict[str, object] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _service_for(self, account: str) -> object:
        from googleapiclient.discovery import build

        name = GoogleAccounts.resolve(account or None)
        if name not in self._services:
            rec = GoogleAccounts.record(name)
            creds = self._load_credentials(rec["calendar_token"])
            self._services[name] = build("calendar", "v3", credentials=creds)
        return self._services[name]

    def forget_account(self, name: str) -> None:
        """Drop the cached service for an account whose token changed or went
        away, so the next call builds one from the token now on disk."""
        self._services.pop(name, None)

    def _accounts(self, account: str) -> typing.List[str]:
        """Accounts to operate on: the named one if given, else every configured
        account (so an unspecified account searches all)."""
        if account:
            return [GoogleAccounts.resolve(account)]
        return GoogleAccounts.list_accounts() or [GoogleAccounts.resolve(None)]

    @staticmethod
    def _event_start_key(event: dict) -> str:
        start = event.get("start", {})
        return start.get("dateTime") or start.get("date") or ""

    def _load_credentials(self, token_file: str) -> typing.Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds: typing.Any = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, _SCOPES
                )
                creds = flow.run_local_server(port=0)
            os.makedirs(os.path.dirname(token_file), exist_ok=True)
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        return creds

    def _cfg(self) -> dict:
        return Config.module_settings("calendar")

    def _fetch_events_range(
        self,
        account: str = "",
        hours_ahead: typing.Optional[int] = None,
        days_back: typing.Optional[int] = None,
        max_results: typing.Optional[int] = None,
        q: typing.Optional[str] = None,
        calendar_id: str = "primary",
        time_min: typing.Optional[str] = None,
        time_max: typing.Optional[str] = None,
    ) -> typing.List[dict]:
        if max_results is None:
            max_results = _DEFAULT_MAX_RESULTS

        now = now_local()

        if time_min and time_max:
            t_min = time_min
            t_max = time_max
        elif days_back is not None:
            t_min = (now - timedelta(days=days_back)).isoformat()
            t_max = now.isoformat()
        else:
            if hours_ahead is None:
                hours_ahead = _DEFAULT_LOOKAHEAD_HOURS
            t_min = now.isoformat()
            t_max = (now + timedelta(hours=hours_ahead)).isoformat()

        items: typing.List[dict] = []
        for name in self._accounts(account):
            service = self._service_for(name)
            kwargs: dict = dict(
                calendarId=calendar_id,
                timeMin=t_min,
                timeMax=t_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            if q:
                kwargs["q"] = q
            response = service.events().list(**kwargs).execute()
            for ev in response.get("items", []):
                ev["_account"] = name
                items.append(ev)

        items.sort(key=self._event_start_key)
        return items

    def _fetch_events_for_day(
        self, day: datetime, account: str = "", calendar_id: str = "primary"
    ) -> typing.List[dict]:
        tz = local_tz()
        start = day.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        end = start + timedelta(days=1)
        items: typing.List[dict] = []
        for name in self._accounts(account):
            service = self._service_for(name)
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=50,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            for ev in response.get("items", []):
                ev["_account"] = name
                items.append(ev)

        items.sort(key=self._event_start_key)
        return items

    def _get_new_events(self, account: str) -> typing.List[dict]:
        name = GoogleAccounts.resolve(account or None)
        cache_key = f"announced_event_ids_{name}"
        events = self._fetch_events_range(account=account)
        announced: typing.List[str] = Cache.get_value(cache_key) or []
        new_events = [e for e in events if e.get("id") not in announced]
        if new_events:
            seen_ids = announced + [e.get("id") for e in new_events if e.get("id")]
            Cache.set_value(cache_key, seen_ids[-200:])
        return new_events

    def agenda_snapshot(self, days: int = 2) -> typing.Dict[str, typing.Any]:
        """Upcoming events as data, for the agenda screen.

        Deliberately not a job: find_events writes prose, and a list with a
        time column and a per-day heading cannot be recovered from prose. Runs
        the same query, keeping the fields instead of describing them.

        Two days by default — an agenda that empties out at 6pm is useless in
        the evening, which is exactly when someone checks tomorrow.
        """
        tz = local_tz()
        start = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=max(1, days))

        events = self._fetch_events_range(
            time_min=start.isoformat(),
            time_max=end.isoformat(),
            max_results=50,
        )

        out = []
        for event in events:
            when = event.get("start", {})
            until = event.get("end", {})
            # Google marks an all-day event by sending "date" instead of
            # "dateTime"; there is no other flag for it.
            all_day = "date" in when and "dateTime" not in when
            out.append(
                {
                    "id": event.get("id", ""),
                    "title": event.get("summary", "Untitled event"),
                    "start": when.get("dateTime") or when.get("date") or "",
                    "end": until.get("dateTime") or until.get("date") or "",
                    "all_day": all_day,
                    "location": event.get("location", ""),
                    "account": event.get("_account", ""),
                }
            )

        return {
            "events": out,
            "today": start.date().isoformat(),
            # The screen groups by day and needs to know which days were asked
            # about, so an empty day reads as "nothing on" and not "not loaded".
            "days": [(start + timedelta(days=i)).date().isoformat() for i in range(max(1, days))],
            "timezone": str(tz),
        }

    def _format_event(self, event: dict, verbose: bool = False) -> str:
        summary = event.get("summary", "Untitled event")
        start = event.get("start", {})
        end = event.get("end", {})
        when = start.get("dateTime") or start.get("date") or ""
        when_end = end.get("dateTime") or end.get("date") or ""
        location = event.get("location", "")
        status = event.get("status", "")

        parts = [f"{summary}"]
        parts.append(f"Start: {self._format_time(when)}")
        if when_end:
            parts.append(f"End: {self._format_time(when_end)}")
        if status and status != "confirmed":
            parts.append(f"Status: {status}")
        if location:
            parts.append(f"Location: {location}")

        if verbose:
            acct = event.get("_account", "")
            if acct and len(GoogleAccounts.list_accounts()) > 1:
                parts.append(f"Account: {acct}")

            description = event.get("description", "").strip()
            if description:
                parts.append(f"Description: {description}")

            organizer = event.get("organizer", {})
            organizer_name = organizer.get("displayName") or organizer.get("email", "")
            if organizer_name:
                parts.append(f"Organizer: {organizer_name}")

            attendees = event.get("attendees", [])
            if attendees:
                attendee_parts = []
                for a in attendees:
                    name = a.get("displayName") or a.get("email", "")
                    resp = a.get("responseStatus", "")
                    attendee_parts.append(f"{name} ({resp})" if resp else name)
                parts.append(f"Attendees: {', '.join(attendee_parts)}")

            meet_link = event.get("hangoutLink", "")
            if not meet_link:
                conf = event.get("conferenceData", {})
                for ep in conf.get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_link = ep.get("uri", "")
                        break
            if meet_link:
                parts.append(f"Meeting link: {meet_link}")

            recurrence = event.get("recurrence", [])
            if recurrence:
                parts.append(f"Recurring: {recurrence[0]}")

            html_link = event.get("htmlLink", "")
            if html_link:
                parts.append(f"Link: {html_link}")

        return "\n  ".join(parts)

    def _format_time(self, value: str) -> str:
        if not value:
            return "unknown time"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
        if "T" not in value:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")

    def _parse_date(self, date_str: str) -> datetime:
        tz = local_tz()
        today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        s = date_str.strip().lower()
        if not s or s == "today":
            return today
        if s == "tomorrow":
            return today + timedelta(days=1)
        if s == "yesterday":
            return today - timedelta(days=1)
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt
        except ValueError:
            return today

    def _parse_time(self, time_str: str, base_date: datetime) -> datetime:
        """Parse 'HH:MM', '2pm', '14:00', etc. relative to base_date."""
        s = time_str.strip().lower()
        is_pm = "pm" in s
        is_am = "am" in s
        s_clean = s.replace("am", "").replace("pm", "").strip()
        if ":" in s_clean:
            parts = s_clean.split(":")
            hour, minute = int(parts[0]), int(parts[1])
        else:
            hour, minute = int(s_clean), 0
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        dt = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz())
        return dt

    def _resolve_calendar_id(
        self, calendar_name: str, account: str
    ) -> typing.Optional[str]:
        service = self._service_for(account)
        cal_list = service.calendarList().list().execute()
        for cal in cal_list.get("items", []):
            if calendar_name.lower() in cal.get("summary", "").lower():
                return cal["id"]
        return None

    def _render_events(
        self,
        events: typing.List[dict],
        header: str,
        count_template: str,
        verbose_override: typing.Optional[bool] = None,
    ) -> str:
        lines = [header]
        lines.append(count_template.format(count=len(events)))
        verbose = True if verbose_override is None else verbose_override
        for event in events:
            lines.append("")
            lines.append(self._format_event(event, verbose=verbose))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    @staticmethod
    def _as_int(value: typing.Any, fallback: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @capture_response
    @method_job
    def find_events(
        self,
        query: str = "",
        date: str = "",
        start_date: str = "",
        end_date: str = "",
        days_back: int = 0,
        hours_ahead: int = 0,
        calendar_name: str = "",
        limit: int = 0,
        account: str = "",
    ) -> str:
        """
        [CALENDAR JOB] Finds calendar events. This is the single tool for every kind of
        event lookup — what's coming up, what's next, a specific day, a date range, the
        past, a keyword search, or a named calendar. With no arguments it returns the
        upcoming events in the configured look-ahead window.

        Use this job when the user wants to:
        - Check their calendar, agenda, or schedule
        - Know what is next, or what is on today/tomorrow/a given date
        - Review past meetings, or events between two dates
        - Search for an event by name, or browse a secondary calendar

        Args:
            query (str): Free-text search over event names and descriptions.
            date (str): A single day: YYYY-MM-DD, or 'today', 'tomorrow', 'yesterday'.
            start_date (str): Start of a date range. Pairs with end_date.
            end_date (str): End of a date range (defaults to a week after start_date).
            days_back (int): Look this many days into the past instead of ahead.
            hours_ahead (int): Look-ahead window in hours (defaults to 24).
            calendar_name (str): Restrict to a named calendar, e.g. 'work', 'family'.
            limit (int): Max events to return. Use 1 for "what's my next event".
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching events with time, title and details.
        """
        max_results = self._as_int(limit) or None

        calendar_id = "primary"
        if calendar_name:
            # Named calendars are account-specific; pin to one account.
            account = GoogleAccounts.resolve(account or None)
            resolved = self._resolve_calendar_id(calendar_name, account)
            if not resolved:
                return f"Calendar '{calendar_name}' not found."
            calendar_id = resolved

        # A single named day is the one case that needs day-boundary fetching.
        if date:
            target = self._parse_date(date)
            label = target.strftime("%Y-%m-%d")
            events = self._fetch_events_for_day(
                target, account=account, calendar_id=calendar_id
            )
            if max_results:
                events = events[:max_results]
            return self._render_events(
                events,
                header=f"Events on {label}:",
                count_template=f"You have {{count}} event(s) on {label}.",
            )

        window = _DEFAULT_MAX_RESULTS * 3
        back = self._as_int(days_back)

        if start_date or end_date:
            start = self._parse_date(start_date) if start_date else now_local()
            end = self._parse_date(end_date) if end_date else start + timedelta(days=7)
            t_min = start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            t_max = end.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
            header = f"Events from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}:"
            events = self._fetch_events_range(
                account=account,
                time_min=t_min,
                time_max=t_max,
                q=query or None,
                calendar_id=calendar_id,
                max_results=max_results or window,
            )
        elif query:
            now = now_local()
            t_min = (now - timedelta(days=back or _SEARCH_DAYS_BACK)).isoformat()
            t_max = (now + timedelta(days=_SEARCH_DAYS_AHEAD)).isoformat()
            header = f"Events matching '{query}':"
            events = self._fetch_events_range(
                account=account,
                q=query,
                time_min=t_min,
                time_max=t_max,
                calendar_id=calendar_id,
                max_results=max_results or window,
            )
        elif back > 0:
            header = f"Events from the past {back} day(s):"
            events = self._fetch_events_range(
                account=account,
                days_back=back,
                calendar_id=calendar_id,
                max_results=max_results,
            )
        else:
            hours = self._as_int(hours_ahead) or None
            # "What's next" asks for one event but shouldn't miss one next week.
            if max_results == 1 and hours is None:
                hours = _DEFAULT_LOOKAHEAD_HOURS * 7
            header = "Upcoming events:"
            events = self._fetch_events_range(
                account=account,
                hours_ahead=hours,
                calendar_id=calendar_id,
                max_results=max_results,
            )

        where = f" in '{calendar_name}'" if calendar_name else ""
        return self._render_events(
            events,
            header=header,
            count_template=f"Found {{count}} event(s){where}.",
        )



    @capture_response
    @method_job
    def start_checking_events(
        self, interval_minutes: int = 0, account: str = ""
    ) -> str:
        """
        [CALENDAR JOB] Starts a background job that checks for new calendar events
        periodically. Announces events as they appear. Stop with 'stop checking calendar'.

        Use this job when the user wants to:
        - Get automatic calendar notifications
        - Monitor the calendar in the background
        - Start periodic agenda polling

        Keywords: start checking calendar, monitor calendar, watch calendar, agenda alerts,
                 background calendar, auto check calendar, notify new event, event reminders

        Args:
            interval_minutes (int): How often to check in minutes (defaults to 15).
            account (str): Google account to monitor (default: primary).

        Returns:
            str: Confirmation that background polling started.
        """
        name = GoogleAccounts.resolve(account or None)
        job_name = _calendar_job_name(name)

        if BackgroundJobs.is_running(job_name):
            return f"Calendar polling for '{name}' is already running."

        if not interval_minutes or interval_minutes <= 0:
            interval_minutes = _DEFAULT_POLL_INTERVAL_MINUTES

        def _poll():
            events = self._get_new_events(name)
            if not events:
                return
            msg = f"You have {len(events)} new calendar event(s) in {name}."
            logger.log_system_event("calendar_poll", msg)
            messages = [msg] + [self._format_event(e, verbose=False) for e in events]
            notify(messages, kind="alert", source="calendar")

        BackgroundJobs.start(job_name, _poll, interval=interval_minutes * 60)
        return f"Checking '{name}' calendar every {interval_minutes} minutes."

    @capture_response
    @method_job
    def stop_checking_events(self, account: str = "") -> str:
        """
        [CALENDAR JOB] Stops the background calendar polling job.

        Use this job when the user wants to:
        - Stop automatic calendar notifications
        - Cancel background calendar monitoring
        - Turn off event reminders

        Keywords: stop checking calendar, stop calendar notifications, cancel calendar monitoring,
                 stop calendar polling, disable event alerts, stop watching calendar

        Args:
            account (str): Account to stop (default: stop all calendar polling).

        Returns:
            str: Confirmation that calendar polling was stopped.
        """
        if account:
            name = GoogleAccounts.resolve(account)
            stopped = BackgroundJobs.stop(_calendar_job_name(name))
            return (
                f"Calendar polling for '{name}' stopped."
                if stopped
                else f"Calendar polling for '{name}' was not running."
            )
        all_jobs = BackgroundJobs.list_jobs()
        cal_jobs = [j for j in all_jobs if j.startswith("calendar_polling_")]
        stopped_any = any(BackgroundJobs.stop(j) for j in cal_jobs)
        return (
            "Calendar polling stopped."
            if stopped_any
            else "Calendar polling was not running."
        )




    @capture_response
    @method_job
    def list_calendars(self, account: str = "") -> str:
        """
        [CALENDAR JOB] Lists all available Google Calendars for the account.

        Use this job when the user wants to:
        - See which calendars they have access to
        - List all calendar names
        - Find a specific calendar by name

        Keywords: my calendars, list calendars, which calendars, show calendars,
                 available calendars, calendar list, all calendars

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: All calendars with their names and IDs.
        """
        service = self._service_for(account)
        cal_list = service.calendarList().list().execute()
        calendars = cal_list.get("items", [])

        if not calendars:
            return "No calendars found."

        lines = [f"Calendars ({len(calendars)}):"]
        for cal in calendars:
            name = cal.get("summary", "Unnamed")
            cal_id = cal.get("id", "")
            primary = " [primary]" if cal.get("primary") else ""
            access = cal.get("accessRole", "")
            lines.append(f"  {name}{primary}  ({access})  id: {cal_id}")
        return "\n".join(lines)


    @capture_response
    @method_job
    def check_availability(
        self, date_str: str = "", start_time: str = "", end_time: str = ""
    ) -> str:
        """
        [CALENDAR JOB] Checks free/busy availability across all Google accounts
        for a given time window.

        Use this job when the user wants to:
        - Know if they are free at a specific time
        - Check availability for a meeting slot
        - See busy blocks across all calendars

        Keywords: am I free, check availability, busy at, free at, do I have time,
                 availability check, when am I free, free slot, check if free

        Args:
            date_str (str): The date to check (default: today).
            start_time (str): Start of the window (e.g. '14:00', '2pm').
            end_time (str): End of the window (e.g. '15:00', '3pm').

        Returns:
            str: Free/busy status per account and overall.
        """
        base = self._parse_date(date_str)

        if start_time:
            t_start = self._parse_time(start_time, base)
        else:
            t_start = base.replace(hour=9, minute=0, second=0, microsecond=0)
            if t_start.tzinfo is None:
                t_start = t_start.replace(tzinfo=local_tz())
        if end_time:
            t_end = self._parse_time(end_time, base)
        else:
            t_end = t_start + timedelta(hours=1)

        t_min = t_start.isoformat()
        t_max = t_end.isoformat()
        window_label = (
            f"{t_start.strftime('%Y-%m-%d %H:%M')} – {t_end.strftime('%H:%M')}"
        )

        accounts = GoogleAccounts.list_accounts()
        if not accounts:
            return "No Google accounts configured."

        all_busy: typing.List[dict] = []
        account_results: typing.List[str] = []

        for acct in accounts:
            try:
                service = self._service_for(acct)
                body = {
                    "timeMin": t_min,
                    "timeMax": t_max,
                    "items": [{"id": "primary"}],
                }
                result = service.freebusy().query(body=body).execute()
                busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
                all_busy.extend(busy)
                status = "busy" if busy else "free"
                account_results.append(
                    f"  {acct}: {status}"
                    + (
                        " — "
                        + ", ".join(
                            f"{b['start'][11:16]}–{b['end'][11:16]}" for b in busy
                        )
                        if busy
                        else ""
                    )
                )
            except Exception as e:
                account_results.append(f"  {acct}: error ({e})")

        overall = "busy" if all_busy else "free"
        lines = [f"Availability for {window_label}: {overall.upper()}"]
        lines.extend(account_results)
        return "\n".join(lines)

    @capture_response
    @method_job
    def find_free_slots(self, date_str: str = "", min_minutes: int = 30) -> str:
        """
        [CALENDAR JOB] Finds free time slots on a given day across all accounts.

        Use this job when the user wants to:
        - Find open time slots for a meeting
        - See when they are free during the day
        - Find a gap in the schedule

        Keywords: free time, open slots, when am I free, find a gap, free slots,
                 available time, find time, when can I meet, schedule gap, open time

        Args:
            date_str (str): The date to check (default: today).
            min_minutes (int): Minimum slot length in minutes (default 30).

        Returns:
            str: Free time slots within working hours across all accounts.
        """
        target = self._parse_date(date_str)
        cfg = self._cfg()
        work_start = int(cfg.get("work_start_hour", 9))
        work_end = int(cfg.get("work_end_hour", 18))

        accounts = GoogleAccounts.list_accounts()
        if not accounts:
            return "No Google accounts configured."

        busy_blocks: typing.List[typing.Tuple[datetime, datetime]] = []
        for acct in accounts:
            try:
                events = self._fetch_events_for_day(target, account=acct)
                for e in events:
                    start_raw = e.get("start", {}).get("dateTime") or e.get(
                        "start", {}
                    ).get("date")
                    end_raw = e.get("end", {}).get("dateTime") or e.get("end", {}).get(
                        "date"
                    )
                    if start_raw and end_raw:
                        try:
                            s = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                            en = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                            if s.tzinfo is None:
                                s = s.replace(tzinfo=local_tz())
                            if en.tzinfo is None:
                                en = en.replace(tzinfo=local_tz())
                            busy_blocks.append((s, en))
                        except ValueError:
                            pass
            except Exception:
                pass

        tz = local_tz()
        day_start = target.replace(
            hour=work_start, minute=0, second=0, microsecond=0, tzinfo=tz
        )
        day_end = target.replace(
            hour=work_end, minute=0, second=0, microsecond=0, tzinfo=tz
        )

        busy_blocks.sort(key=lambda x: x[0])
        merged: typing.List[typing.Tuple[datetime, datetime]] = []
        for s, e in busy_blocks:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        free_slots: typing.List[str] = []
        cursor = day_start
        for s, e in merged:
            if s > cursor:
                gap_minutes = int((s - cursor).total_seconds() / 60)
                if gap_minutes >= min_minutes:
                    free_slots.append(
                        f"{cursor.strftime('%H:%M')} – {s.strftime('%H:%M')} ({gap_minutes} min)"
                    )
            if e > cursor:
                cursor = e
        if cursor < day_end:
            gap_minutes = int((day_end - cursor).total_seconds() / 60)
            if gap_minutes >= min_minutes:
                free_slots.append(
                    f"{cursor.strftime('%H:%M')} – {day_end.strftime('%H:%M')} ({gap_minutes} min)"
                )

        label = target.strftime("%Y-%m-%d")
        if not free_slots:
            return f"No free slots of {min_minutes}+ minutes found on {label}."

        lines = [
            f"Free slots on {label} (working hours {work_start}:00–{work_end}:00):"
        ]
        for slot in free_slots:
            lines.append(f"  {slot}")
        return "\n".join(lines)


    @capture_response
    @method_job
    def get_week_agenda(self, account: str = "") -> str:
        """
        [CALENDAR JOB] Retrieves this week's calendar agenda (next 7 days).

        Use this job when the user wants to:
        - See all events for the coming week
        - Get the weekly schedule or agenda
        - Plan the week ahead

        Keywords: week agenda, this week schedule, weekly events, next 7 days,
                 week calendar, week meetings, weekly agenda, what's this week

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: All events for the next 7 days.
        """
        events = self._fetch_events_range(
            account=account, hours_ahead=168, max_results=_DEFAULT_MAX_RESULTS * 3
        )
        return self._render_events(
            events,
            header="This week's agenda (next 7 days):",
            count_template="This week you have {count} event(s).",
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def _write_allowed(self) -> bool:
        return bool(self._cfg().get("allow_write", False))

    def _write_disabled_note(self) -> str:
        return (
            "Calendar writes are disabled (allow_write: false). "
            "To enable: set modules.calendar.allow_write: true in config.yaml.\n"
            "Note: delete credentials/calendar_token_*.json first to re-authenticate with the new scope."
        )

    @capture_response
    @method_job
    def create_event(
        self,
        title: str,
        date: str = "",
        start_time: str = "",
        end_time: str = "",
        description: str = "",
        location: str = "",
        calendar_name: str = "",
        account: str = "",
    ) -> str:
        """
        [CALENDAR JOB] Creates a new event on Google Calendar.

        Use this job when the user wants to:
        - Add a meeting, appointment, or reminder to the calendar
        - Schedule an event
        - Create a calendar entry

        Keywords: create event, add event, schedule meeting, add to calendar,
                 new appointment, book meeting, add meeting, schedule appointment

        Args:
            title (str): Event title or name. (required)
            date (str): Date of the event (e.g. 'today', 'tomorrow', '2025-03-15'). Provide date or start_time.
            start_time (str): Start time (e.g. '2pm', '14:00', '9:30am'). Provide date or start_time.
            end_time (str): End time (e.g. '3pm', '15:00'). Defaults to 1 hour after start.
            description (str): Optional description or notes for the event.
            location (str): Optional location or meeting link.
            calendar_name (str): Name of the calendar to add to (default: primary).
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation with event details, or an error message.
        """
        if not title:
            return "Error: Event title is required."
        if not date and not start_time:
            return "Error: At least a date or start time is required."

        base = (
            self._parse_date(date)
            if date
            else now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        if start_time:
            start_dt = self._parse_time(start_time, base)
        else:
            start_dt = base.replace(hour=9, minute=0, second=0, microsecond=0)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=local_tz())

        if end_time:
            end_dt = self._parse_time(end_time, base)
        else:
            end_dt = start_dt + timedelta(hours=1)

        if not self._write_allowed():
            lines = [
                self._write_disabled_note(),
                "",
                "Event details to create manually in Google Calendar:",
                f"  Title:       {title}",
                f"  Date:        {start_dt.strftime('%Y-%m-%d')}",
                f"  Start time:  {start_dt.strftime('%H:%M')}",
                f"  End time:    {end_dt.strftime('%H:%M')}",
            ]
            if description:
                lines.append(f"  Description: {description}")
            if location:
                lines.append(f"  Location:    {location}")
            if calendar_name:
                lines.append(f"  Calendar:    {calendar_name}")
            return "\n".join(lines)

        calendar_id = "primary"
        if calendar_name:
            resolved = self._resolve_calendar_id(calendar_name, account)
            if resolved:
                calendar_id = resolved

        # isoformat() carries the UTC offset, which is all Google Calendar needs
        # — no separate timeZone field.
        start_entry: typing.Dict[str, str] = {"dateTime": start_dt.isoformat()}
        end_entry: typing.Dict[str, str] = {"dateTime": end_dt.isoformat()}

        event_body: typing.Dict[str, typing.Any] = {
            "summary": title,
            "start": start_entry,
            "end": end_entry,
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location

        service = self._service_for(account)
        try:
            created = (
                service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                )
                .execute()
            )
        except Exception as e:
            return f"Failed to create event: {e}"

        start_str = self._format_time(
            created["start"].get("dateTime", created["start"].get("date", ""))
        )
        return f"Event created: '{title}' on {start_str}."

    @capture_response
    @method_job
    def edit_event(
        self,
        query: str = "",
        date: str = "",
        new_title: str = "",
        new_date: str = "",
        new_start_time: str = "",
        new_end_time: str = "",
        new_description: str = "",
        new_location: str = "",
        account: str = "",
    ) -> str:
        """
        [CALENDAR JOB] Edits an existing calendar event.

        Use this job when the user wants to:
        - Change the time, title, or details of an existing event
        - Reschedule a meeting
        - Update event description or location

        Keywords: edit event, update event, reschedule, change meeting time,
                 move event, update calendar, change appointment

        Args:
            query (str): Search query or event title to find the event. Provide query or date (at least one required).
            date (str): Date to search on (narrows the search). Provide query or date (at least one required).
            new_title (str): New title for the event (leave empty to keep current).
            new_date (str): New date (leave empty to keep current).
            new_start_time (str): New start time (leave empty to keep current).
            new_end_time (str): New end time (leave empty to keep current).
            new_description (str): New description (leave empty to keep current).
            new_location (str): New location (leave empty to keep current).
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation of the update, or an error message.
        """
        if not query and not date:
            return "Error: Provide a query or date to find the event to edit."

        # Edits patch a specific calendar; pin to one account for search + patch.
        account = GoogleAccounts.resolve(account or None)
        search_date = self._parse_date(date) if date else None
        if search_date:
            events = self._fetch_events_for_day(search_date, account=account)
        else:
            events = self._fetch_events_range(
                account=account, hours_ahead=720, max_results=50, q=query
            )

        if query:
            events = [
                e for e in events if query.lower() in e.get("summary", "").lower()
            ]

        if not events:
            return "No matching event found."

        event = events[0]
        event_id = event["id"]
        current_title = event.get("summary", "(untitled)")
        patch: typing.Dict[str, typing.Any] = {}

        if new_title:
            patch["summary"] = new_title
        if new_description:
            patch["description"] = new_description
        if new_location:
            patch["location"] = new_location

        if new_date or new_start_time or new_end_time:
            old_start_str = event.get("start", {}).get("dateTime") or event.get(
                "start", {}
            ).get("date", "")
            try:
                old_start = datetime.fromisoformat(old_start_str.replace("Z", "+00:00"))
                if old_start.tzinfo is None:
                    old_start = old_start.replace(tzinfo=local_tz())
            except Exception:
                old_start = now_local()

            base = (
                self._parse_date(new_date)
                if new_date
                else old_start.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            start_dt = (
                self._parse_time(new_start_time, base) if new_start_time else old_start
            )
            if new_end_time:
                end_dt = self._parse_time(new_end_time, base)
            else:
                old_end_str = event.get("end", {}).get("dateTime") or event.get(
                    "end", {}
                ).get("date", "")
                try:
                    old_end = datetime.fromisoformat(old_end_str.replace("Z", "+00:00"))
                    end_dt = start_dt + (old_end - old_start)
                except Exception:
                    end_dt = start_dt + timedelta(hours=1)

            start_entry: typing.Dict[str, str] = {"dateTime": start_dt.isoformat()}
            end_entry: typing.Dict[str, str] = {"dateTime": end_dt.isoformat()}
            patch["start"] = start_entry
            patch["end"] = end_entry

        if not patch:
            return "Nothing to update — provide at least one new value."

        if not self._write_allowed():
            lines = [
                self._write_disabled_note(),
                "",
                f"Changes to apply manually to '{current_title}' in Google Calendar:",
            ]
            if "summary" in patch:
                lines.append(f"  New title:       {patch['summary']}")
            if "start" in patch:
                lines.append(f"  New start time:  {patch['start']['dateTime']}")
                lines.append(f"  New end time:    {patch['end']['dateTime']}")
            if "description" in patch:
                lines.append(f"  New description: {patch['description']}")
            if "location" in patch:
                lines.append(f"  New location:    {patch['location']}")
            return "\n".join(lines)

        service = self._service_for(account)
        try:
            updated = (
                service.events()
                .patch(
                    calendarId="primary",
                    eventId=event_id,
                    body=patch,
                )
                .execute()
            )
        except Exception as e:
            return f"Failed to update event: {e}"

        return f"Event updated: '{updated.get('summary', current_title)}'."

    @capture_response
    @method_job
    def delete_event(
        self,
        query: str = "",
        date: str = "",
        account: str = "",
    ) -> str:
        """
        [CALENDAR JOB] Deletes a calendar event. Requires confirmation from the user.

        Use this job when the user wants to:
        - Delete or cancel a calendar event
        - Remove a meeting from the calendar

        Keywords: delete event, remove event, cancel meeting, delete calendar entry,
                 cancel appointment, remove from calendar

        Args:
            query (str): Event title or search query to find the event. Provide query or date (at least one required).
            date (str): Date to search on (narrows the search). Provide query or date (at least one required).
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation that the event was deleted, or an error message.
        """
        if not query and not date:
            return "Error: Provide a query or date to find the event to delete."

        # Deletes target a specific calendar; pin to one account.
        account = GoogleAccounts.resolve(account or None)
        search_date = self._parse_date(date) if date else None
        if search_date:
            events = self._fetch_events_for_day(search_date, account=account)
        else:
            events = self._fetch_events_range(
                account=account, hours_ahead=720, max_results=50, q=query
            )

        if query:
            events = [
                e for e in events if query.lower() in e.get("summary", "").lower()
            ]

        if not events:
            return "No matching event found."

        if len(events) > 1:
            titles = [e.get("summary", "(untitled)") for e in events[:5]]
            return (
                f"Found {len(events)} matching events. Be more specific. "
                f"First matches: {', '.join(titles)}"
            )

        event = events[0]
        event_id = event["id"]
        title = event.get("summary", "(untitled)")
        start_str = self._format_time(
            event.get("start", {}).get("dateTime")
            or event.get("start", {}).get("date", "")
        )

        if not self._write_allowed():
            return (
                f"{self._write_disabled_note()}\n\n"
                f"Event to delete manually in Google Calendar:\n"
                f"  Title: {title}\n"
                f"  Start: {start_str}"
            )

        service = self._service_for(account)
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
        except Exception as e:
            return f"Failed to delete event: {e}"

        return f"Event deleted: '{title}'."
