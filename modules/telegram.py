"""Telegram: talk to Wony from a phone.

Wony polls Telegram over outbound HTTPS, so nothing listens on this machine and
no public address is needed. Messages from the paired chat run through the same
run_turn() as voice and the web page; timers, reminders and alerts are pushed
back to that chat. It registers no jobs, so it costs the model nothing.

It only works while Wony is running. Telegram holds messages for 24 hours, and
one older than _STALE_SECONDS gets "I was off" instead of being acted on —
"turn off the lights" from last night must not run this morning.
"""
import datetime
import os
import secrets
import threading
import time
import typing

import requests

from helpers import events, net
from helpers.config import Config
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.memory_db import get_kv, set_kv
from helpers.notify import notify
from helpers.registry import ServiceRegistry, register_service
from helpers.requirements import Requirement

_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_JOB = "telegram"
_API = "https://api.telegram.org"
_OFFSET_KEY = "telegram.offset"
_CODE_KEY = "telegram.pairing_code"

# Telegram holds a getUpdates request open this long waiting for a message, so
# the read timeout has to outlast it.
_POLL_SECONDS = 30
_POLL_HTTP_TIMEOUT = (3.0, _POLL_SECONDS + 10.0)
_FILE_HTTP_TIMEOUT = (3.0, 30.0)

# Older than this, a message was sent while Wony was off (or paused).
_STALE_SECONDS = 600
# A backlog of stale messages gets one "I was off" reply, not one each.
_STALE_NOTICE_GAP = 60

# Telegram's limit is 4096, counted in UTF-16 units; emoji count double.
_MAX_MESSAGE_CHARS = 4000

# A long note keeps the one polling loop busy transcribing.
_MAX_VOICE_SECONDS = 120

# Wrong pairing codes tolerated before pairing is off until Wony restarts.
_MAX_PAIR_ATTEMPTS = 5

_MIN_BACKOFF = 2.0
_MAX_BACKOFF = 120.0
_CONFLICT_WAIT = 60.0

_FORWARD_PROMPT = (
    "I forwarded this message to you. Summarize it, and ask me what to do if it "
    "needs a reply or an action."
)

# A pause then resume starts a second loop while the first is still inside its
# long poll; two pollers on one token make Telegram answer 409.
_loop_lock = threading.Lock()


class TelegramError(Exception):
    """A failed Bot API call. code 0 means the network, not Telegram."""

    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"Telegram error {code}: {description}")
        self.code = code


class _Request(typing.NamedTuple):
    text: str
    # Someone else's words the user forwarded; fenced by run_turn.
    quoted: str = ""
    # What a voice note was heard as, echoed back so a misheard word shows.
    heard: str = ""


def _owner() -> str:
    return str(Config.get("modules.telegram.owner", "") or "").strip()


def _chunks(text: str, limit: int = _MAX_MESSAGE_CHARS) -> typing.List[str]:
    """Split on paragraph, line or word boundaries so no piece passes `limit`."""
    pieces: typing.List[str] = []
    rest = text.strip()
    while len(rest) > limit:
        cut = -1
        for separator in ("\n\n", "\n", " "):
            # Searching from 1: a cut at 0 would make no progress.
            cut = rest.rfind(separator, 1, limit)
            if cut > 0:
                break
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def _forward(payload: typing.Dict[str, typing.Any]) -> None:
    """events listener: copy a notification to the phone.

    Runs on whichever thread raised it, so the send gets its own thread.
    """
    if payload.get("type") != "notification" or payload.get("source") == "telegram":
        return
    bot = ServiceRegistry.get_service_instance("telegram")
    text = str(payload.get("text") or "")
    if bot is None or not text:
        return
    threading.Thread(target=bot.push, args=(text,), daemon=True, name="telegram-push").start()


@register_service(
    module_name="telegram",
    requires=Requirement(
        env_vars=[_TOKEN_ENV],
        setup_hint="In Telegram, message @BotFather, send /newbot, and paste the token it gives you.",
    ),
)
class Telegram:
    def __init__(self) -> None:
        self._token = os.environ[_TOKEN_ENV]
        self._username = ""
        self._code: typing.Optional[str] = None
        self._wrong_codes = 0
        self._warned: typing.Set[str] = set()
        self._last_stale_notice = 0.0
        # A re-init must not leave the old listener forwarding everything twice.
        events.unsubscribe(_forward)
        events.subscribe(_forward)

    def start(self) -> bool:
        """Begin polling. Called from bootstrap, not __init__: any process that
        merely imports modules (the tests, `doctor`) would otherwise start
        taking the real bot's messages."""
        return BackgroundJobs.start(_JOB, self._run, pass_stop_event=True)

    # ------------------------------------------------------------ Bot API

    def _call(
        self,
        method: str,
        http_timeout: typing.Optional[typing.Tuple[float, float]] = None,
        **params: typing.Any,
    ) -> typing.Any:
        # The token is in the URL, and requests puts the URL in its error
        # messages — so no exception from here is allowed to carry one.
        kwargs = {"timeout": http_timeout} if http_timeout else {}
        try:
            response = net.post(f"{_API}/bot{self._token}/{method}", json=params, **kwargs)
        except requests.RequestException:
            raise TelegramError(0, "network error") from None
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(response.status_code, "unreadable reply") from None
        if not body.get("ok"):
            raise TelegramError(
                int(body.get("error_code") or response.status_code),
                str(body.get("description") or ""),
            )
        return body.get("result")

    def _download(self, file_path: str) -> bytes:
        try:
            response = net.get(f"{_API}/file/bot{self._token}/{file_path}", timeout=_FILE_HTTP_TIMEOUT)
        except requests.RequestException:
            raise TelegramError(0, "network error") from None
        if response.status_code != 200:
            raise TelegramError(response.status_code, "could not download the file")
        return response.content

    def _send(self, chat_id: str, text: str) -> None:
        for piece in _chunks(text):
            self._call(
                "sendMessage",
                chat_id=chat_id,
                text=piece,
                link_preview_options={"is_disabled": True},
            )

    def push(self, text: str) -> None:
        """Send a proactive message to the paired chat. Never raises."""
        owner = _owner()
        # Not running means paused (or the token was refused): stay quiet.
        if not owner or not BackgroundJobs.is_running(_JOB):
            return
        if not Config.get("modules.telegram.forward_notifications", True):
            return
        try:
            self._send(owner, text)
        except TelegramError as exc:
            logger.log_error(str(exc), "telegram.push")

    # --------------------------------------------------------------- loop

    def _run(self, stop: threading.Event) -> None:
        while not _loop_lock.acquire(timeout=1.0):
            if stop.is_set():
                return
        try:
            delay = _MIN_BACKOFF
            while not stop.is_set():
                try:
                    self._poll_once(stop)
                except TelegramError as exc:
                    if exc.code == 401:
                        self._warn_once(
                            "token",
                            "Telegram refused the bot token. Paste it again in Settings, then restart Wony.",
                        )
                        return
                    if exc.code == 409:
                        self._warn_once(
                            "conflict",
                            "Another program is already collecting this bot's messages, "
                            "maybe Wony on another computer. Only one can at a time.",
                        )
                        stop.wait(_CONFLICT_WAIT)
                        continue
                    logger.log_error(str(exc), "telegram.poll")
                except Exception as exc:
                    logger.log_error(str(exc), "telegram.poll")
                else:
                    delay = _MIN_BACKOFF
                    continue
                stop.wait(delay)
                delay = min(delay * 2, _MAX_BACKOFF)
        finally:
            _loop_lock.release()

    def _poll_once(self, stop: threading.Event) -> None:
        # Resolved here, not at startup: no network at boot must not end this.
        if not self._username:
            self._username = str(self._call("getMe")["username"])
        self._offer_pairing()

        params: typing.Dict[str, typing.Any] = {
            "timeout": _POLL_SECONDS,
            "allowed_updates": ["message"],
        }
        offset = int(get_kv(_OFFSET_KEY, "0") or 0)
        if offset:
            params["offset"] = offset
        updates = self._call("getUpdates", http_timeout=_POLL_HTTP_TIMEOUT, **params)
        # Paused mid-poll: leave them unconfirmed so the next run sees them.
        if stop.is_set():
            return

        for update in updates:
            try:
                self._handle(update)
            except Exception as exc:
                logger.log_error(str(exc), "telegram.handle")
            # Advance even when handling failed, or one bad message is
            # redelivered forever.
            set_kv(_OFFSET_KEY, str(int(update["update_id"]) + 1))

    def _warn_once(self, key: str, text: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        notify(text, kind="error", source="telegram")

    # ------------------------------------------------------------ pairing

    def _offer_pairing(self) -> None:
        if _owner() or self._code is not None or self._wrong_codes >= _MAX_PAIR_ATTEMPTS:
            return
        # Kept until someone pairs: the announcement is one spoken sentence and
        # one bell entry, and a restart must not turn the one you saw into a lie.
        self._code = get_kv(_CODE_KEY, "")
        if not self._code:
            self._code = f"{secrets.randbelow(10**6):06d}"
            set_kv(_CODE_KEY, self._code)
        notify(
            f"To connect Telegram, send /start {self._code} to @{self._username}.",
            kind="info",
            source="telegram",
        )

    def _retire_code(self) -> None:
        self._code = None
        set_kv(_CODE_KEY, "")

    def setting_note(self, key: str) -> str:
        """Live text for the Settings page under 'Paired chat': the code to send.
        Shown on the page only. It lets whoever has it control Wony, so the
        assistant is never told it (see settings._live_note)."""
        if key != "modules.telegram.owner" or _owner():
            return ""
        if self._code is not None:
            return f"Waiting for you: send /start {self._code} to @{self._username} in Telegram."
        if self._wrong_codes >= _MAX_PAIR_ATTEMPTS:
            return "Pairing is off after too many wrong codes. Restart Wony for a new one."
        return ""

    def _try_pair(self, chat_id: str, text: str) -> None:
        # Strangers get no reply at all, right or wrong.
        parts = text.split()
        if self._code is None or len(parts) != 2 or parts[0] != "/start":
            return
        if not secrets.compare_digest(parts[1].encode(), self._code.encode()):
            self._wrong_codes += 1
            if self._wrong_codes >= _MAX_PAIR_ATTEMPTS:
                # Retired, not just paused: five guesses must not be five
                # steps through a code that stays the same after a restart.
                self._retire_code()
                notify(
                    "Someone sent the wrong Telegram pairing code several times. "
                    "Pairing is off until Wony restarts.",
                    kind="alert",
                    source="telegram",
                )
            return

        from helpers import settings

        try:
            settings.apply({"modules.telegram.owner": chat_id})
        except Exception as exc:
            logger.log_error(str(exc), "telegram.pair")
            self._send(chat_id, "I couldn't save that. Check Wony's Settings page and try again.")
            return
        self._retire_code()
        name =str(Config.get("assistant.name", "Wony") or "Wony")
        self._send(chat_id, f"Connected. This is {name}: ask me anything you'd ask at the computer.")

    # ----------------------------------------------------------- messages

    def _handle(self, update: typing.Dict[str, typing.Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        chat_id = str(chat.get("id", ""))
        owner = _owner()
        if not owner:
            self._try_pair(chat_id, message.get("text") or "")
        elif chat_id == owner:
            self._answer(chat_id, message)

    def _answer(self, chat_id: str, message: typing.Dict[str, typing.Any]) -> None:
        from helpers.conversation import Conversation, sanitize_calls
        from helpers.turn import run_turn
        from helpers.untrusted import truncate, wrap

        sent_at = float(message.get("date") or 0)
        if time.time() - sent_at > _STALE_SECONDS:
            self._tell_stale(chat_id, sent_at)
            return

        request = self._read(chat_id, message)
        if request is None:
            return

        try:
            self._call("sendChatAction", chat_id=chat_id, action="typing")
        except TelegramError:
            pass  # cosmetic

        result = run_turn(request.text, at_machine=False, quoted=request.quoted)
        reply = result.text.strip() or "Done."
        if request.heard:
            reply = f"Heard: \"{request.heard}\"\n\n{reply}"
        self._send(chat_id, reply)
        if result.error:
            return

        # The web page shows the exchange too. A forwarded message stays
        # fenced in the history the next turn reads.
        recorded = request.text
        if request.quoted:
            recorded += "\n" + wrap(truncate(request.quoted, 500), "forwarded message")
        Conversation.record_turn(recorded, result.text, calls=sanitize_calls(result.calls))

    def _tell_stale(self, chat_id: str, sent_at: float) -> None:
        now = time.time()
        if now - self._last_stale_notice < _STALE_NOTICE_GAP:
            return
        self._last_stale_notice = now
        when = datetime.datetime.fromtimestamp(sent_at).strftime("%a %H:%M")
        self._send(
            chat_id,
            f"You sent this on {when}, while I was off, so I haven't done it. "
            "Send it again if you still want it.",
        )

    def _read(self, chat_id: str, message: typing.Dict[str, typing.Any]) -> typing.Optional[_Request]:
        """The request in a message, or None once it has been answered here."""
        voice = message.get("voice")
        heard = ""
        if voice:
            heard = self._transcribe(chat_id, voice) or ""
            text = heard
            if not text:
                return None
        else:
            text = (message.get("text") or "").strip()
            if not text:
                self._send(chat_id, "I can read text and voice notes.")
                return None
        if text == "/start":
            self._send(chat_id, "I'm here. Ask me anything you'd ask at the computer.")
            return None
        if message.get("forward_origin"):
            return _Request(_FORWARD_PROMPT, quoted=text)
        return _Request(text, heard=heard)

    def _transcribe(self, chat_id: str, voice: typing.Dict[str, typing.Any]) -> typing.Optional[str]:
        if (voice.get("duration") or 0) > _MAX_VOICE_SECONDS:
            self._send(chat_id, f"That voice note is too long. Keep it under {_MAX_VOICE_SECONDS // 60} minutes.")
            return None
        try:
            from helpers.recognizer import transcribe_audio_bytes

            info = self._call("getFile", file_id=voice["file_id"])
            text, warning = transcribe_audio_bytes(self._download(info["file_path"]), suffix=".ogg")
        except ImportError:
            self._send(
                chat_id,
                "Voice isn't installed on this computer, so I can only read text. "
                "Run install.bat again and tick Voice I/O.",
            )
            return None
        except Exception as exc:
            logger.log_error(str(exc), "telegram.voice")
            self._send(chat_id, "I couldn't listen to that voice note.")
            return None
        if not text:
            self._send(chat_id, f"{warning} Try again." if warning else "I couldn't make out that voice note.")
            return None
        return text
