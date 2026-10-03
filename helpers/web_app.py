"""
FastAPI app factory. Call build_app() after bootstrap() has run.
Serves the JSON API, the WebSocket the screen listens on, and — once
`kiosk/dist` has been built — the touch UI itself.
"""

import asyncio
import json
import os
import typing

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from helpers.config import Config
from helpers.registry import ServiceRegistry


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



def _sanitize_calls(
    calls: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Ensure every call is JSON-serializable (coerce non-serializable args to str)."""
    safe = []
    for c in calls:
        safe_args: typing.Dict[str, typing.Any] = {}
        for k, v in (c.get("args") or {}).items():
            try:
                json.dumps(v)
                safe_args[k] = v
            except (TypeError, ValueError):
                safe_args[k] = str(v)
        safe.append({"name": c.get("name", ""), "args": safe_args, "result": str(c.get("result", ""))})
    return safe


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


class KioskTilesRequest(BaseModel):
    tiles: typing.List[str] = []


class SleepRequest(BaseModel):
    # "07:00", "8h", "90m", an ISO datetime, or blank for "until someone
    # touches the screen".
    wake_at: str = ""


class SettingsRequest(BaseModel):
    updates: typing.Dict[str, typing.Any] = {}
    # None leaves the enabled modules alone; a list replaces them.
    modules: typing.Optional[typing.List[str]] = None


_LOOPBACK = ("127.0.0.1", "localhost")


class _LocalOnlyMiddleware:
    """Refuse requests a website could have made on the user's behalf.

    The API has no password, so any page open in a browser could otherwise post
    to it or open /api/ws (browsers do not apply CORS to WebSockets). The Host
    check stops DNS rebinding; the Origin check stops cross-site requests. A
    screen on another machine (server.host set to this device's address) is
    the same site as far as its own page is concerned, so it still works.
    """

    def __init__(self, app: typing.Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: typing.Any, send: typing.Any) -> None:
        if scope["type"] in ("http", "websocket") and not _allowed(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                from fastapi.responses import JSONResponse

                await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _allowed(scope: dict) -> bool:
    from urllib.parse import urlsplit

    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    host = headers.get("host", "")
    configured = str(Config.get("server.host", "127.0.0.1"))
    # Bound to every interface, any name may reach it; only Origin can be checked.
    if configured not in ("0.0.0.0", "::") and host.rsplit(":", 1)[0] not in _LOOPBACK + (configured,):
        return False
    # Belt and suspenders alongside the Origin check: a fetch() a site makes to
    # this server is neither same-origin nor absent, whatever Origin it sends.
    if headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return False
    origin = headers.get("origin")
    if not origin:
        return True  # not a browser: no website can drive it
    # The Vite dev server rewrites its proxied requests' Origin to this
    # server's own (kiosk/vite.config.ts), so it needs no carve-out here.
    return urlsplit(origin).netloc == host


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
        return {
            "assistant": {
                "name": Config.get("assistant.name", "Wony"),
            },
            "kiosk": {
                "idle_minutes": Config.get("kiosk.idle_minutes", 15),
                "home_columns": Config.get("kiosk.home_columns", 3),
                "confirm_all_devices": Config.get("kiosk.confirm_all_devices", False),
            },
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

        diagnostics: typing.List[typing.Dict] = []
        try:
            from helpers.diagnostics import get_all
            diagnostics = get_all()
        except Exception:
            pass

        return {
            "provider": provider,
            "model": model_name,
            "modules": modules_out,
            "diagnostics": diagnostics,
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
                    "destructive": bool(declared),
                    "confirm_words": confirm_words,
                    "parameters": {
                        "properties": properties,
                        "required": required,
                    },
                }
            )

        return {"jobs": jobs_out}

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

        if ServiceRegistry.job_confirms(req.name):
            # Deliberately not routed through helpers/confirm.py: the tap
            # already passed the UI's confirm dialog and the user is watching
            # the result. Logged separately so the audit trail says which of
            # these ran from a button rather than from the model.
            logger.log_system_event("web_invoke_confirmed", req.name)

        logger.log_function_call(req.name, "[web]", coerced)
        try:
            # Same lock every agent turn takes — a button press reaches the same
            # jobs and the same Conversation state as a typed sentence.
            from helpers.decorators import agent_lock, set_agent_active
            from helpers.turn_context import user_request

            # A tap is the user asking, so a Sign in again button may open
            # Google's consent page.
            with agent_lock, user_request():
                set_agent_active(True)
                try:
                    result = func(**coerced)
                finally:
                    set_agent_active(False)
            result_str = str(result) if result is not None else ""
            logger.log_function_response(req.name, result_str[:200], "[web]")
            return {"ok": True, "result": result_str}
        except Exception as e:
            err = str(e)
            logger.log_error(err, f"web_invoke.{req.name}")
            return {"ok": False, "result": "", "error": err}

    @app.post("/api/chat")
    def chat(req: ChatRequest) -> typing.Dict[str, typing.Any]:
        from helpers.conversation import Conversation
        from helpers.logger import logger
        from helpers.turn import run_turn

        if not req.message or not req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        result = run_turn(req.message)
        if result.error is not None:
            logger.log_error(result.error, "web_chat")
            raise HTTPException(status_code=503, detail=result.error)

        safe_calls = _sanitize_calls(result.calls)
        turn_id = Conversation.record_turn(req.message, result.text, calls=safe_calls)
        return {"id": turn_id, "text": result.text, "calls": safe_calls}

    @app.get("/api/kiosk/tiles")
    def get_kiosk_tiles() -> typing.Dict[str, typing.Any]:
        """The saved home-screen layout, or null when nobody has arranged one yet."""
        from helpers.kiosk import load_tiles

        return {"tiles": load_tiles()}

    @app.post("/api/kiosk/tiles")
    def set_kiosk_tiles(req: KioskTilesRequest) -> typing.Dict[str, typing.Any]:
        """Save the home-screen layout. Each id is `kind` or `kind:arg`."""
        from helpers.kiosk import save_tiles

        try:
            save_tiles(req.tiles)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"tiles": req.tiles}

    @app.get("/api/ambient")
    def get_ambient() -> typing.Dict[str, typing.Any]:
        """Cards for the idle screen. Cached server-side; safe to poll."""
        from helpers.kiosk import ambient

        return {"cards": ambient()}

    @app.get("/api/sleep")
    def sleep_status() -> typing.Dict[str, typing.Any]:
        """Whether the device is asleep, and when it plans to wake."""
        from helpers import lowpower

        return lowpower.status()

    @app.post("/api/sleep")
    def sleep_start(req: SleepRequest) -> typing.Dict[str, typing.Any]:
        """Go dark. The processes behind this response keep running."""
        from helpers import lowpower

        try:
            return lowpower.enter(wake_at=req.wake_at, reason="screen")
        except lowpower.WakeTimeError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/wake")
    def sleep_end() -> typing.Dict[str, typing.Any]:
        """Come back. The screen posts this on any touch while asleep, so it is
        deliberately harmless to call when nothing is asleep."""
        from helpers import lowpower

        return lowpower.wake(reason="touch")

    @app.get("/api/panels")
    def list_panels() -> typing.Dict[str, typing.Any]:
        """Which panels this install has, given the modules that are on."""
        from helpers.panels import available

        return {"panels": available()}

    @app.get("/api/panel/{key}")
    def get_panel(key: str) -> typing.Dict[str, typing.Any]:
        """Structured data for one screen — weather, agenda, timers, devices,
        music, accounts. The write side of every panel goes through /api/invoke
        like any other job; only reading needs a shape."""
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
        lamps called 'Lamp'. The screen already knows which one was tapped.
        """
        if "home_assistant" not in Config.enabled_modules():
            raise HTTPException(status_code=503, detail="Home Assistant is not enabled.")

        from helpers.logger import logger
        from modules import home_assistant

        logger.log_function_call(
            "control_device", "[screen]", {"entity_id": req.entity_id, "action": req.action}
        )
        try:
            ok, text = home_assistant.control(
                req.entity_id, req.action, req.value, req.option
            )
        except Exception as e:
            logger.log_error(str(e), "web_control_device")
            raise HTTPException(status_code=502, detail=str(e))

        logger.log_function_response("control_device", text[:200], "[screen]")
        return {"ok": ok, "text": text}

    @app.get("/api/notifications")
    def list_notifications(
        include_acknowledged: bool = False,
        limit: int = 50,
    ) -> typing.Dict[str, typing.Any]:
        """Proactive messages the screen has not shown yet (newest first)."""
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

    @app.get("/api/updates")
    def check_updates() -> typing.Dict[str, str]:
        """Whether a newer Wony is waiting. Never pulls — see helpers/updates.py."""
        from helpers.updates import check

        return {"message": check()}

    @app.post("/api/chat/clear")
    def clear_chat() -> typing.Dict[str, str]:
        from helpers.conversation import Conversation

        Conversation.clear()
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

    @app.get("/api/chat/history")
    def chat_history(limit: int = 50) -> typing.Dict[str, typing.Any]:
        from helpers.memory_db import recent_turns

        turns = recent_turns(min(limit, 200))
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
        stay in sync without a separate SSE connection.
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
            from helpers.conversation import Conversation
            from helpers.logger import logger
            from helpers.turn import run_turn

            try:
                result = run_turn(message, on_text=lambda c: q.put(("delta", c)))
                if result.error:
                    logger.log_error(result.error, "ws_chat")
                    q.put(("error", result.error))
                    return

                safe_calls = _sanitize_calls(result.calls)
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

    _dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kiosk", "dist")

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
                # Without it the browser only has ETag and Last-Modified, so it
                # falls back to heuristic freshness and may serve this shell
                # from disk without asking — which pins the screen to whichever
                # hashed bundle it named when it was cached. Rebuilding and
                # restarting the service would then change nothing visible,
                # because the stale shell is the thing choosing the bundle.
                # The bundles themselves are content-hashed, so they are safe
                # to cache; only this file must never go stale.
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            return JSONResponse({"detail": "Not found"}, status_code=404)

    return app
