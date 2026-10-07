"""
FastAPI app factory. Call build_app() after bootstrap() has run.
The app is built in-process by the unified web entry point and the tray host.
"""

import asyncio
import json
import os
import typing

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from helpers import local_only
from helpers.config import Config
from helpers.registry import ServiceRegistry

# The built UI (not in the repo). A constant so a test can point it elsewhere.
_DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")


def _coerce_args(
    func: typing.Callable,
    raw: typing.Dict[str, typing.Any],
) -> typing.Dict[str, typing.Any]:
    from helpers.tools import _parse_signature

    _, properties, _ = _parse_signature(func)

    coerced: typing.Dict[str, typing.Any] = {}
    for key, value in raw.items():
        if value == "" or value is None:
            continue
        prop_type = properties.get(key, {}).get("type", "string")
        try:
            if prop_type == "integer":
                coerced[key] = int(value)
            elif prop_type == "number":
                coerced[key] = float(value)
            elif prop_type == "boolean":
                if isinstance(value, bool):
                    coerced[key] = value
                else:
                    coerced[key] = str(value).lower() in ("true", "1", "yes", "on")
            elif prop_type == "array":
                if isinstance(value, list):
                    coerced[key] = value
                else:
                    try:
                        parsed = json.loads(value)
                        coerced[key] = parsed if isinstance(parsed, list) else [parsed]
                    except (json.JSONDecodeError, TypeError):
                        coerced[key] = [
                            v.strip() for v in str(value).split(",") if v.strip()
                        ]
            elif prop_type == "object":
                if isinstance(value, dict):
                    coerced[key] = value
                else:
                    coerced[key] = json.loads(value)
            else:
                coerced[key] = str(value)
        except (ValueError, TypeError):
            coerced[key] = value

    return coerced


class InvokeRequest(BaseModel):
    name: str
    args: typing.Dict[str, typing.Any] = {}


class ChatRequest(BaseModel):
    message: str


class DeviceControlRequest(BaseModel):
    entity_id: str
    action: str = "toggle"
    # A slider position, or a named mode picked from the device's own options.
    value: typing.Optional[float] = None
    option: str = ""


class SettingsRequest(BaseModel):
    updates: typing.Dict[str, typing.Any] = {}
    # None leaves the enabled modules alone; a list replaces them.
    modules: typing.Optional[typing.List[str]] = None


class Pin(BaseModel):
    id: str
    kind: typing.Literal["run", "toggle", "presets", "slider", "input"]
    job: str
    module: str = ""
    title: str
    args: typing.Dict[str, typing.Any] = {}


class PinsRequest(BaseModel):
    pins: typing.List[Pin]


_PINS_KV_KEY = "web.pins"

# Saved dashboard pins outlive the jobs they name. A pin for a job that was
# merged into another is pointed at its replacement rather than left dead.
_RETIRED_PIN_JOBS: typing.Dict[str, typing.Dict[str, typing.Any]] = {
    "watch_inbox": {"job": "manage_triggers", "module": "status", "args": {"name": "new_email"}},
    "watch_calendar": {"job": "manage_triggers", "module": "status", "args": {"name": "new_event"}},
    "list_mcp_servers": {"job": "manage_mcp_server", "args": {"action": "list"}},
    "click_at": {"job": "click", "args": {}},
    "click_text": {"job": "click", "args": {}},
    "close_computer": {"job": "power", "args": {"action": "shutdown"}},
    "fetch_url": {"job": "browse", "args": {}},
    "find_contact": {"job": "contact", "args": {"action": "find"}},
}


def _migrate_pins(pins: typing.List[typing.Dict[str, typing.Any]]) -> typing.List[typing.Dict[str, typing.Any]]:
    out = []
    for pin in pins:
        replacement = _RETIRED_PIN_JOBS.get(pin.get("job", ""))
        out.append({**pin, **replacement} if replacement else pin)
    return out


def _allowed_hosts() -> typing.Optional[typing.Tuple[str, ...]]:
    """The host names this server answers to; None means any."""
    return local_only.LOOPBACK_NAMES


class _LocalOnlyMiddleware:
    """Refuse requests a website could have made on the user's behalf
    (helpers/local_only.py)."""

    def __init__(self, app: typing.Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: typing.Any, send: typing.Any) -> None:
        if scope["type"] in ("http", "websocket") and not local_only.allowed(scope, _allowed_hosts()):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_app() -> FastAPI:
    """Build and return the FastAPI application. Must be called after bootstrap()."""
    from contextlib import asynccontextmanager

    _ws_clients: typing.Set[WebSocket] = set()
    _ws_loop: typing.Optional[asyncio.AbstractEventLoop] = None

    async def _ws_broadcast(message: dict) -> None:
        dead: typing.List[WebSocket] = []
        for ws in list(_ws_clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients.discard(ws)

    def _on_event(payload: dict) -> None:
        loop = _ws_loop
        if loop is None or not _ws_clients:
            return
        try:
            asyncio.run_coroutine_threadsafe(_ws_broadcast(payload), loop)
        except Exception:
            pass

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        nonlocal _ws_loop
        _ws_loop = asyncio.get_running_loop()
        from helpers.events import subscribe, unsubscribe

        subscribe(_on_event)
        try:
            yield
        finally:
            unsubscribe(_on_event)

    # No docs/OpenAPI: this API has no auth, so the schema is one more thing
    # a page in the browser could fetch to learn what is callable.
    app = FastAPI(
        title="Wony Web API", lifespan=_lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    app.add_middleware(_LocalOnlyMiddleware)

    @app.get("/api/config")
    def get_config() -> typing.Dict[str, typing.Any]:
        """Return frontend-relevant config values."""
        from helpers import restart
        from helpers.audio import _MAX_CAPTURE_SECONDS

        return {
            "assistant": {
                "name": Config.get("assistant.name", "Wony"),
            },
            "can_restart": restart.available(),
            "voice": {
                "stt": {
                    "silence_ms": int(Config.get("voice.stt.silence_ms", 700)),
                    "max_seconds": int(_MAX_CAPTURE_SECONDS),
                },
            },
        }

    @app.post("/api/restart")
    def restart_app() -> typing.Dict[str, str]:
        from helpers import restart

        if not restart.request():
            raise HTTPException(
                status_code=409,
                detail="Wony wasn't started from the tray icon, so it can't restart itself. Close it and start it again.",
            )
        return {"status": "restarting"}

    @app.get("/api/capabilities")
    def get_capabilities() -> typing.Dict[str, typing.Any]:
        """What Wony can do right now, and what's switched off but available —
        the one source behind the chat chips and the welcome card."""
        from helpers.settings import capabilities

        caps = capabilities()
        return {
            "working": [cap._asdict() for cap in caps["working"]],
            "available": [cap._asdict() for cap in caps["available"]],
        }

    @app.get("/api/health")
    def health() -> typing.Dict[str, typing.Any]:
        status = ServiceRegistry.get_module_status()
        hints = ServiceRegistry.get_module_hints()
        model_info = None
        try:
            from helpers.model import get_model

            model_info = get_model()
        except Exception:
            pass

        provider = model_info[0] if model_info else "unknown"
        from helpers.model import current_model_name

        model_name = current_model_name(provider)

        modules_out: typing.Dict[str, typing.Any] = {}
        for name, (st, reason) in status.items():
            modules_out[name] = {
                "status": st,
                "reason": reason,
                "hint": hints.get(name, ""),
            }

        compute: typing.Dict[str, typing.Any] = {}
        try:
            from helpers.compute import compute_status
            compute = compute_status()
        except Exception:
            pass

        diagnostics: typing.List[typing.Dict] = []
        try:
            from helpers.diagnostics import get_all
            diagnostics = get_all()
        except Exception:
            pass

        background: typing.List[str] = []
        try:
            from helpers.jobs import BackgroundJobs
            background = BackgroundJobs.list_jobs()
        except Exception:
            pass

        watching: typing.Dict[str, bool] = {}
        try:
            from helpers import triggers
            watching = {t.name: triggers.is_on(t.name) for t in triggers.all_triggers()}
        except Exception:
            pass

        return {
            "provider": provider,
            "model": model_name,
            "modules": modules_out,
            "compute": compute,
            "diagnostics": diagnostics,
            "background": background,
            "triggers": watching,
        }

    @app.get("/api/jobs")
    def list_jobs() -> typing.Dict[str, typing.Any]:
        from helpers.tools import _parse_signature

        all_jobs = ServiceRegistry.get_all_jobs()
        job_modules = ServiceRegistry.get_job_modules()
        job_summaries = ServiceRegistry.get_job_summaries()
        confirms = ServiceRegistry.get_job_confirms()

        jobs_out = []
        for name, func in all_jobs.items():
            try:
                description, properties, required = _parse_signature(func)
            except Exception:
                description, properties, required = "", {}, []

            declared = confirms.get(name)
            # True (or a truthy anything-but-a-collection) means every call
            # confirms, so there is no fixed word list to hand the UI — only a
            # set/list of gate words narrows it to specific `action` values.
            confirm_words = (
                sorted(str(v).lower() for v in declared)
                if isinstance(declared, (set, frozenset, list, tuple))
                else None
            )

            jobs_out.append(
                {
                    "name": name,
                    "module": job_modules.get(name, ""),
                    "summary": job_summaries.get(name, ""),
                    "description": description,
                    "confirms": bool(declared),
                    "confirm_words": confirm_words,
                    "parameters": {
                        "properties": properties,
                        "required": required,
                    },
                }
            )

        return {"jobs": jobs_out}

    @app.get("/api/panels")
    def list_panels() -> typing.Dict[str, typing.Any]:
        """Which panels this install has, given the modules that are on."""
        from helpers.panels import available

        return {"panels": available()}

    @app.get("/api/panel/{key}")
    def get_panel(key: str) -> typing.Dict[str, typing.Any]:
        """Structured data for one panel. The write side of every panel goes
        through /api/invoke like any other job; only reading needs a shape."""
        from helpers.panels import PanelUnavailable, panel

        try:
            return panel(key)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No panel '{key}'.")
        except PanelUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            from helpers.logger import logger

            logger.log_error(str(e), f"web_panel.{key}")
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/devices/control")
    def control_device(req: DeviceControlRequest) -> typing.Dict[str, typing.Any]:
        """Act on one Home Assistant device by its exact id.

        The one panel with a write path, and the reason it is not /api/invoke:
        control_home_device resolves a spoken name, which would toggle both
        lamps called 'Lamp'. The UI already knows which one was pressed.
        """
        if "home_assistant" not in Config.enabled_modules():
            raise HTTPException(status_code=503, detail="Home Assistant is not enabled.")

        from helpers.logger import logger
        from modules import home_assistant

        logger.log_function_call(
            "control_device", "[web]", {"entity_id": req.entity_id, "action": req.action}
        )
        try:
            ok, text = home_assistant.control(
                req.entity_id, req.action, req.value, req.option
            )
        except Exception as e:
            logger.log_error(str(e), "web_device_control")
            raise HTTPException(status_code=502, detail=str(e))

        logger.log_function_response("control_device", text[:200], "[web]")
        return {"ok": ok, "text": text}

    @app.get("/api/notifications")
    def list_notifications(
        include_acknowledged: bool = False,
        limit: int = 50,
    ) -> typing.Dict[str, typing.Any]:
        """Proactive messages the user has not seen yet (newest first)."""
        from helpers.memory_db import all_notifications

        return {
            "notifications": all_notifications(
                include_acknowledged=include_acknowledged,
                limit=min(limit, 200),
            )
        }

    @app.post("/api/notifications/{notification_id}/ack")
    def ack_notification(notification_id: int) -> typing.Dict[str, str]:
        from helpers.memory_db import acknowledge_notification

        if not acknowledge_notification(notification_id):
            raise HTTPException(
                status_code=404, detail=f"No notification {notification_id}."
            )
        return {"status": "acknowledged"}

    @app.post("/api/notifications/ack-all")
    def ack_all_notifications() -> typing.Dict[str, int]:
        from helpers.memory_db import acknowledge_all_notifications

        return {"cleared": acknowledge_all_notifications()}

    @app.get("/api/settings")
    def get_settings() -> typing.Dict[str, typing.Any]:
        from helpers.settings import describe

        return describe()

    @app.post("/api/settings")
    def save_settings(req: SettingsRequest) -> typing.Dict[str, typing.Any]:
        from helpers.logger import logger
        from helpers.settings import SettingsError, apply

        try:
            result = apply(req.updates, req.modules)
        except SettingsError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.log_error(str(e), "web_settings")
            raise HTTPException(status_code=500, detail=f"Could not save settings: {e}")

        if result["written"]:
            logger.log_system_event("settings_changed", ", ".join(result["written"]))
        return result

    @app.get("/api/pins")
    def get_pins() -> typing.Dict[str, typing.Any]:
        from helpers.memory_db import get_kv

        raw = get_kv(_PINS_KV_KEY, "")
        if not raw:
            return {"pins": None}
        try:
            return {"pins": _migrate_pins(json.loads(raw))}
        except (json.JSONDecodeError, ValueError):
            return {"pins": None}

    @app.post("/api/pins")
    def save_pins(req: PinsRequest) -> typing.Dict[str, typing.Any]:
        from helpers.memory_db import set_kv

        all_jobs = ServiceRegistry.get_all_jobs()
        unknown = sorted({p.job for p in req.pins if p.job not in all_jobs})
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"Unknown job(s): {', '.join(unknown)}"
            )

        pins = [p.model_dump() for p in req.pins]
        set_kv(_PINS_KV_KEY, json.dumps(pins))
        return {"pins": pins}

    @app.post("/api/invoke")
    def invoke_job(req: InvokeRequest) -> typing.Dict[str, typing.Any]:
        from helpers.logger import logger

        all_jobs = ServiceRegistry.get_all_jobs()
        func = all_jobs.get(req.name)
        if func is None:
            raise HTTPException(status_code=404, detail=f"Job '{req.name}' not found")

        try:
            coerced = _coerce_args(func, req.args)
        except Exception as e:
            raise HTTPException(
                status_code=422, detail=f"Argument coercion failed: {e}"
            )

        gated = ServiceRegistry.job_confirms(req.name)
        if gated:
            # Deliberately not routed through helpers/confirm.py: the button
            # already passed the UI's confirm dialog and the user is watching
            # the result. Logged separately so the audit trail says which of
            # these ran from a button rather than from the model.
            logger.log_system_event("web_invoke_confirmed", req.name)

        logger.log_function_call(req.name, "[web]", coerced)
        try:
            # Same lock every agent turn takes — a button press reaches the same
            # jobs and the same Conversation state as a typed sentence.
            from helpers import confirm
            from helpers.conversation import Conversation
            from helpers.decorators import agent_lock, set_agent_active
            from helpers.turn_context import user_request

            # A button press is the user asking, so a Sign in again button may open
            # Google's consent page.
            with agent_lock, user_request():
                if gated:
                    # The model may have armed this same call; the click spends it.
                    confirm.disarm(req.name, coerced)
                set_agent_active(True)
                try:
                    result = func(**coerced)
                finally:
                    set_agent_active(False)
                result_str = str(result) if result is not None else ""
                if gated:
                    Conversation.record_confirmed(req.name, coerced, result_str)
            logger.log_function_response(req.name, result_str[:200], "[web]")
            return {"ok": True, "result": result_str}
        except Exception as e:
            err = str(e)
            logger.log_error(err, f"web_invoke.{req.name}")
            return {"ok": False, "result": "", "error": err}

    @app.post("/api/chat")
    def chat(req: ChatRequest) -> typing.Dict[str, typing.Any]:
        from helpers.conversation import Conversation, sanitize_calls
        from helpers.logger import logger
        from helpers.turn import run_turn

        if not req.message or not req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        result = run_turn(req.message, think=True)
        if result.error is not None:
            logger.log_error(result.error, "web_chat")
            raise HTTPException(status_code=503, detail=result.error)

        safe_calls = sanitize_calls(result.calls)
        turn_id = Conversation.record_turn(req.message, result.text, calls=safe_calls)
        return {"id": turn_id, "text": result.text, "calls": safe_calls}


    @app.post("/api/chat/clear")
    def clear_chat() -> typing.Dict[str, str]:
        from helpers.conversation import Conversation
        from helpers.memory_db import mark_chat_cleared

        Conversation.clear()
        mark_chat_cleared()
        return {"status": "cleared"}

    @app.post("/api/data/wipe")
    def wipe_data() -> typing.Dict[str, str]:
        from helpers.cache import Cache
        from helpers.logger import logger
        from helpers.memory_db import wipe_all

        try:
            wipe_all()
            Cache.wipe()
            logger.wipe_logs()
            return {"status": "wiped"}
        except Exception as e:
            logger.log_error(str(e), "web_wipe_data")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/ack")
    def play_ack() -> typing.Dict[str, bool]:
        """Play the 'Yes?' acknowledgement chime through PC speakers.
        A plain def: playback blocks, and FastAPI runs these on a worker thread."""
        try:
            from helpers.audio import Audio
            Audio.play_cached("Yes?")
        except Exception:
            pass
        return {"ok": True}

    @app.post("/api/stt")
    async def stt_from_audio(request: Request) -> typing.Dict[str, typing.Any]:
        """Decode uploaded audio (webm/opus from MediaRecorder) → text via Whisper."""
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="No audio data received.")
        try:
            from starlette.concurrency import run_in_threadpool

            from helpers.recognizer import transcribe_audio_bytes

            # Seconds of Whisper on the event loop would freeze every chat stream.
            text, warning = await run_in_threadpool(transcribe_audio_bytes, data)
            if warning:
                return {
                    "text": "",
                    "warning": f"{warning} Check the browser's mic permission and Windows input device.",
                }
            return {"text": text}
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Voice isn't installed. Run install.bat again and tick Voice I/O.",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Couldn't turn that into text: {e}")

    @app.get("/api/chat/history")
    def chat_history(limit: int = 50) -> typing.Dict[str, typing.Any]:
        from helpers.memory_db import visible_turns

        turns = visible_turns(min(limit, 200))
        return {
            "turns": [
                {
                    "id": t["id"],
                    "user": t["user_text"],
                    "assistant": t["assistant_text"],
                    "ts": t["ts"],
                    "calls": t.get("calls", []),
                }
                for t in turns
            ]
        }

    async def _ws_chat(ws: WebSocket, data: dict) -> None:
        """Handle a {type:"chat"} message on the WebSocket.

        Streams deltas back to the requesting client only, then broadcasts the
        completed turn (with session_id) to all connected clients so other tabs
        and the voice UI stay in sync without a separate SSE connection.
        """
        import queue as _queue
        import threading as _threading
        from datetime import datetime as _dt

        message = (data.get("message") or "").strip()
        session_id = str(data.get("session_id") or "")

        if not message:
            try:
                await ws.send_json({"type": "error", "session_id": session_id, "data": "Message cannot be empty."})
            except Exception:
                pass
            return

        q: "_queue.Queue" = _queue.Queue()
        loop = asyncio.get_running_loop()

        def _run() -> None:
            from helpers.conversation import Conversation, sanitize_calls
            from helpers.logger import logger
            from helpers.turn import run_turn

            try:
                result = run_turn(message, on_text=lambda c: q.put(("delta", c)), think=True)
                if result.error:
                    logger.log_error(result.error, "ws_chat")
                    q.put(("error", result.error))
                    return

                safe_calls = sanitize_calls(result.calls)
                # emit=False: we broadcast ourselves below with session_id included
                turn_id = Conversation.record_turn(message, result.text, calls=safe_calls, emit=False)
                q.put(("done", {
                    "id": turn_id,
                    "user": message,
                    "assistant": result.text,
                    "calls": safe_calls,
                    "ts": _dt.now().isoformat(timespec="seconds"),
                }))
            except Exception as e:
                logger.log_error(str(e), "ws_chat")
                q.put(("error", str(e)))
            finally:
                q.put(None)

        _threading.Thread(target=_run, daemon=True, name="ws-chat").start()

        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            kind, payload = item
            try:
                if kind == "delta":
                    await ws.send_json({"type": "delta", "session_id": session_id, "data": payload})
                elif kind == "done":
                    await _ws_broadcast({"type": "turn", "session_id": session_id, **payload})
                elif kind == "error":
                    await ws.send_json({"type": "error", "session_id": session_id, "data": payload})
            except Exception:
                break

    @app.websocket("/api/ws")
    async def websocket_turns(ws: WebSocket) -> None:
        await ws.accept()
        _ws_clients.add(ws)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if data.get("type") == "chat":
                    asyncio.create_task(_ws_chat(ws, data))
                elif data.get("type") == "stop":
                    from helpers.events import request_cancel
                    request_cancel()
        except WebSocketDisconnect:
            pass
        finally:
            _ws_clients.discard(ws)

    _dist = _DIST_DIR

    if os.path.isdir(_dist):
        _assets = os.path.join(_dist, "assets")
        if os.path.isdir(_assets):
            app.mount("/assets", StaticFiles(directory=_assets), name="assets")

        @app.exception_handler(404)
        async def spa_fallback(
            request: Request, exc: HTTPException
        ) -> FileResponse | JSONResponse:
            if request.url.path.startswith("/api"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            index = os.path.join(_dist, "index.html")
            if os.path.isfile(index):
                # no-cache means "revalidate every time", not "never store".
                # Without it the browser may serve this shell from disk, and a
                # stale shell keeps naming the old hashed bundle after a rebuild.
                # The bundles are content-hashed and safe to cache; this is not.
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            return JSONResponse({"detail": "Not found"}, status_code=404)

    return app
