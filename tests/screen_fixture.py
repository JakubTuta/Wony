"""A stand-in for Wony's API with fixed data, for running the touch panel
without the assistant behind it.

    python tests/screen_fixture.py 8765      # then: python wony.py panel --windowed
                                              #   (with server.port 8765), or
                                              #   qml6 kiosk/Main.qml -- --api http://127.0.0.1:8765 --windowed

tests/test_screen.py starts the same server on a free port and loads the panel
against it.
"""
import contextlib
import datetime
import socket
import struct
import sys
import threading
import time
import typing
import zlib

import uvicorn
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from helpers import local_only


DEFAULT_TILES = ["device:light.lamp", "device:cover.blinds", "device:lock.front",
                 "routine:good night", "timer:10", "volume"]


def _control(entity_id: str, name: str, domain: str, **extra: typing.Any) -> dict:
    base = {
        "entity_id": entity_id, "name": name, "domain": domain, "state": "off", "on": False,
        "available": True, "level": None, "options": [], "press": False, "number": False,
        "toggle": False, "slider": False, "guarded": False, "target": None, "current": None,
    }
    base.update(extra)
    return base


def _device(name: str, **control: typing.Any) -> dict:
    entity_id = control.pop("entity_id")
    domain = control.pop("domain")
    return {"name": name, "primary": _control(entity_id, name, domain, **control), "extras": []}


def _devices() -> dict:
    return {
        "locks_allowed": True,
        "areas": [
            {"name": "Living room", "devices": [
                _device("Floor lamp", entity_id="light.lamp", domain="light", state="on", on=True,
                        toggle=True, slider=True, level=70),
                _device("Blinds", entity_id="cover.blinds", domain="cover", state="open", on=True, level=100),
                _device("Thermostat", entity_id="climate.main", domain="climate", state="heat", on=True,
                        target=21.5, current=20.5),
                _device("Robot vacuum", entity_id="vacuum.robo", domain="vacuum", state="docked"),
            ]},
            {"name": "Hallway", "devices": [
                _device("Front door", entity_id="lock.front", domain="lock", state="locked", guarded=True),
                _device("Doorbell chime", entity_id="button.chime", domain="button", press=True, state="unknown"),
                _device("Scene", entity_id="select.mode", domain="select", state="Home",
                        options=["Home", "Away", "Night"]),
            ]},
            {"name": "", "devices": [
                _device("Humidity target", entity_id="number.hum", domain="number", state="45", number=True),
            ]},
        ],
    }


def _soon(minutes: int) -> str:
    return (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")


_SETTINGS = {
    "sections": [
        {"title": "Assistant", "fields": [
            {"key": "assistant.name", "label": "Name", "kind": "text", "help": "What it answers to.",
             "choices": [], "min": None, "max": None, "step": None, "restart": False, "value": "Wony"},
            {"key": "assistant.provider", "label": "AI provider", "kind": "choice", "help": "",
             "choices": ["gemini", "openai", "ollama"], "min": None, "max": None, "step": None,
             "restart": True, "value": "gemini"},
            {"key": "kiosk.idle_minutes", "label": "Idle screen after (minutes)", "kind": "number",
             "help": "0 turns it off.", "choices": [], "min": 0, "max": 120, "step": 5, "restart": False,
             "value": 15},
            {"key": "kiosk.confirm_all", "label": "Confirm every device action", "kind": "toggle",
             "help": "", "choices": [], "min": None, "max": None, "step": None, "restart": False,
             "value": False},
            {"key": "assistant.about", "label": "About me", "kind": "longtext", "help": "Shared with the AI.",
             "choices": [], "min": None, "max": None, "step": None, "restart": False, "value": ""},
        ]},
    ],
    "modules": [
        {"key": "weather", "label": "Weather", "help": "Forecast on the home screen.", "enabled": True},
        {"key": "gmail", "label": "Gmail", "help": "Read and draft mail.", "enabled": False},
    ],
    "config_file": "config.yaml",
}


def _cover_png(size: int = 96) -> bytes:
    """A small diagonal gradient, so the album-art path has a real image to decode."""
    filter_none = bytes([0])
    rows = b"".join(
        filter_none + b"".join(bytes((x * 255 // size, y * 255 // size, 160)) for x in range(size))
        for y in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    signature = bytes([137]) + b"PNG" + bytes([13, 10, 26, 10])
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class _LocalOnly:
    """The guard the real server has (helpers/local_only.py), so the panel is
    tested against it: a QML request that sent a foreign Origin would be refused
    here as it would be on the device. Also records every path asked for."""

    def __init__(self, app: typing.Any, seen: list) -> None:
        self.app = app
        self.seen = seen

    async def __call__(self, scope: dict, receive: typing.Any, send: typing.Any) -> None:
        if scope["type"] in ("http", "websocket"):
            self.seen.append(scope["path"])
            if not local_only.allowed(scope, local_only.LOOPBACK_NAMES):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_fixture_app(origin: str = "") -> FastAPI:
    """`origin` is where this app is served, so the playing track can point at its own cover."""
    app = FastAPI()
    # posted: what the panel changed; seen: every path it asked for.
    state: dict = {"tiles": list(DEFAULT_TILES), "posted": [], "seen": []}
    app.state.fixture = state

    app.add_middleware(_LocalOnly, seen=state["seen"])

    @app.get("/api/config")
    def config() -> dict:
        return {"assistant": {"name": "Wony"},
                "kiosk": {"idle_minutes": 15, "home_columns": 3, "confirm_all_devices": False}}

    @app.get("/api/kiosk/tiles")
    def get_tiles() -> dict:
        return {"tiles": state["tiles"]}

    @app.post("/api/kiosk/tiles")
    def set_tiles(body: dict) -> dict:
        state["tiles"] = body["tiles"]
        return {"tiles": state["tiles"]}

    @app.get("/api/ambient")
    def ambient() -> dict:
        return {"cards": [{"key": "quote", "label": "Today", "text": "Water the plants and call Mum."}]}

    @app.get("/api/notifications")
    def notifications(include_acknowledged: bool = False) -> dict:
        return {"notifications": [
            {"id": 1, "kind": "reminder", "source": "reminders", "text": "Take the bins out"},
            {"id": 2, "kind": "alert", "source": "google", "text": "Google signed me out of 'work'."},
        ]}

    @app.post("/api/notifications/{notification_id}/ack")
    def ack(notification_id: int) -> dict:
        return {"status": "ok"}

    @app.post("/api/notifications/ack-all")
    def ack_all() -> dict:
        return {"acknowledged": 2}

    @app.get("/api/sleep")
    def sleep_status() -> dict:
        return {"asleep": False, "since": None, "wake_at": None, "display": "", "paused_jobs": [],
                "last_wake": "07:00"}

    @app.post("/api/sleep")
    def sleep_start(body: dict) -> dict:
        state["posted"].append(("sleep", body))
        return {"asleep": True, "since": _soon(0), "wake_at": None, "display": "none", "paused_jobs": [],
                "last_wake": body.get("wake_at") or ""}

    @app.post("/api/wake")
    def wake() -> dict:
        return {"asleep": False, "since": None, "wake_at": None, "display": "", "paused_jobs": [],
                "last_wake": None}

    panels: dict = {
        "weather": {"city": "Kraków", "description": "Light rain", "temperature": 14.2, "feels_like": 12.0,
                    "unit": "C", "humidity": 80, "wind": 3.1, "wind_unit": "m/s", "icon": "10d",
                    "condition": 500, "sunrise": None, "sunset": None, "error": None},
        "agenda": {"events": [
            {"id": "e1", "title": "Dentist", "start": _soon(95), "end": _soon(125), "all_day": False,
             "location": "Main St", "account": "personal"},
            {"id": "e2", "title": "Team sync", "start": _soon(400), "end": _soon(430), "all_day": False,
             "location": "", "account": "work"},
        ], "today": datetime.date.today().isoformat(), "days": [datetime.date.today().isoformat()],
            "timezone": "Europe/Warsaw"},
        "reminders": {"reminders": [
            {"id": "r1", "text": "10 minute timer", "action_job": "", "when_str": "in 10 minutes",
             "repeating": False, "next_run": _soon(7)},
            {"id": "r2", "text": "Call the plumber", "action_job": "", "when_str": "at 18:00",
             "repeating": False, "next_run": _soon(30)},
        ]},
        "routines": {"routines": [
            {"name": "good night", "steps": "Turn off the lights, lock the front door, set the alarm."},
            {"name": "movie time", "steps": "Dim the lamp, close the blinds and start the TV."},
        ]},
        "devices": _devices(),
        "music": {"active": True, "is_playing": True, "title": "Everything In Its Right Place",
                  "artist": "Radiohead", "album": "Kid A", "art_url": origin + "/art.png" if origin else None, "progress_ms": 61000,
                  "duration_ms": 251000, "shuffle": False, "liked": True, "device": "Kitchen", "volume": 40},
        "music_library": {"devices": [{"name": "Kitchen", "active": True}, {"name": "Bedroom", "active": False}],
                          "playlists": [{"name": "Morning"}, {"name": "Focus"}, {"name": "Dinner"},
                                        {"name": "Roadtrip"}]},
        "accounts": {"accounts": [
            {"name": "personal", "email": "me@example.com", "primary": True, "signed_in": True,
             "needs_sign_in": False, "modules": {"gmail": True, "calendar": True},
             "signed_in_at": "2026-10-01T09:00:00"},
            {"name": "work", "email": "", "primary": False, "signed_in": False, "needs_sign_in": True,
             "modules": {"gmail": False, "calendar": False}, "signed_in_at": ""},
        ], "primary": "personal", "services": {"gmail": True, "calendar": True}, "credentials_ready": True},
    }

    @app.get("/art.png")
    def art() -> Response:
        return Response(_cover_png(), media_type="image/png")

    @app.get("/api/panel/{key}")
    def panel(key: str) -> dict:
        return panels[key]

    @app.post("/api/devices/control")
    def control(body: dict) -> dict:
        state["posted"].append(("control", body))
        return {"ok": True, "text": "Done."}

    @app.get("/api/settings")
    def settings() -> dict:
        return _SETTINGS

    @app.post("/api/settings")
    def save_settings(body: dict) -> dict:
        state["posted"].append(("settings", body))
        return {"written": list(body.get("updates", {})), "restart_required": False}

    @app.get("/api/updates")
    def updates() -> dict:
        return {"message": "You are on the latest version."}

    @app.get("/api/jobs")
    def jobs() -> dict:
        return {"jobs": []}

    @app.post("/api/invoke")
    def invoke(body: dict) -> dict:
        state["posted"].append(("invoke", body))
        return {"ok": True, "result": "Done."}

    @app.websocket("/api/ws")
    async def ws(socket_: WebSocket) -> None:
        await socket_.accept()
        try:
            while True:
                data = await socket_.receive_json()
                if data.get("type") == "chat":
                    state["posted"].append(("chat", data["message"]))
                    await socket_.send_json({"type": "turn", "session_id": data.get("session_id"),
                                             "id": 1, "user": data["message"], "assistant": "Okay.",
                                             "ts": _soon(0)})
        except WebSocketDisconnect:
            pass

    return app


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def serve(port: int = 0) -> typing.Iterator[typing.Tuple[str, FastAPI]]:
    """Run the fixture API in a thread; yields (base url, app)."""
    port = port or free_port()
    app = build_fixture_app(f"http://127.0.0.1:{port}")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    chosen = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    with serve(chosen) as (url, _):
        print(f"Fixture API on {url} - Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
