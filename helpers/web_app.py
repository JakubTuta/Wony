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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from helpers.config import Config
from helpers.registry import ServiceRegistry

# Jobs the web UI flags before invoking. Not a config key — a user editing this
# list is a code change, not a setting.
_DESTRUCTIVE_JOBS: typing.Set[str] = {
    "exit",
    "power_off",
    "reboot",
    "stop_active_jobs",
    "send_email",
    "reply_to_email",
    "mark_as_read",
    "create_event",
    "edit_event",
    "delete_event",
    # scheduler
    "cancel_reminder",
    "edit_reminder",
    # gmail write
    "delete_email",
    "delete_draft",
    "edit_draft",
    # accounts
    "remove_google_account",
    "edit_google_account",
    # Discards the stored token before re-running consent: an interrupted
    # sign-in leaves the account worse off than it started.
    "authorize_google_account",
}


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
    brightness_percent: typing.Optional[int] = None


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

    app = FastAPI(title="Wony Web API", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/config")
    def get_config() -> typing.Dict[str, typing.Any]:
        """Return frontend-relevant config values."""
        return {
            "assistant": {
                "name": Config.get("assistant.name", "Wony"),
                "language": Config.get("assistant.language", "en"),
            },
            "kiosk": {
                "idle_minutes": Config.get("kiosk.idle_minutes", 15),
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
        if provider == "anthropic":
            model_name = Config.get("ai.anthropic_model") or "claude (auto)"
        elif provider == "gemini":
            model_name = Config.get("ai.gemini_model") or "gemini (auto)"
        elif provider == "ollama":
            model_name = Config.get("ai.ollama_model") or "ollama"
        else:
            model_name = None

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
        destructive = _DESTRUCTIVE_JOBS

        jobs_out = []
        for name, func in all_jobs.items():
            try:
                description, properties, required = _parse_signature(func)
            except Exception:
                description, properties, required = "", {}, []

            jobs_out.append(
                {
                    "name": name,
                    "module": job_modules.get(name, ""),
                    "summary": job_summaries.get(name, ""),
                    "description": description,
                    "destructive": name in destructive,
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

        logger.log_function_call(req.name, "[web]", coerced)
        try:
            result = func(**coerced)
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
        from helpers.turn import run_turn

        if not req.message or not req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        result = run_turn(req.message)
        if result.error is not None:
            raise HTTPException(status_code=503, detail=result.error)

        safe_calls = _sanitize_calls(result.calls)
        turn_id = Conversation.record_turn(req.message, result.text, calls=safe_calls)
        return {"id": turn_id, "text": result.text, "calls": safe_calls}

    @app.get("/api/tiles")
    def list_tiles() -> typing.Dict[str, typing.Any]:
        """The home-screen manifest for the touch UI."""
        from helpers.kiosk import tiles

        return {"tiles": tiles()}

    @app.post("/api/tiles/{tile_id}")
    def run_tile_endpoint(tile_id: str) -> typing.Dict[str, typing.Any]:
        """Run one tile. A job tile answers without involving the model at all."""
        from helpers.kiosk import run_tile

        try:
            result = run_tile(tile_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No tile '{tile_id}'.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": result.ok, "text": result.text, "source": result.source}

    @app.get("/api/ambient")
    def get_ambient() -> typing.Dict[str, typing.Any]:
        """Cards for the idle screen. Cached server-side; safe to poll."""
        from helpers.kiosk import ambient

        return {"cards": ambient()}

    @app.get("/api/panel/{key}")
    def get_panel(key: str) -> typing.Dict[str, typing.Any]:
        """Structured data for one screen — weather, agenda, devices, music,
        accounts. The write side of every panel goes through /api/invoke like
        any other job; only reading needs a shape."""
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
                req.entity_id, req.action, req.brightness_percent
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

    @app.post("/api/chat/clear")
    def clear_chat() -> typing.Dict[str, str]:
        from helpers.conversation import Conversation

        Conversation.clear()
        return {"status": "cleared"}

    @app.post("/api/data/wipe")
    def wipe_data() -> typing.Dict[str, str]:
        from helpers.logger import logger
        from helpers.memory_db import wipe_all

        try:
            wipe_all()
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
            from helpers.turn import run_turn

            try:
                result = run_turn(message, on_text=lambda c: q.put(("delta", c)))
                if result.error is not None:
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
