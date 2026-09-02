"""
FastAPI app factory. Call build_app() after bootstrap() has run.
The app is built in-process by the unified web entry point and the tray host.
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
    "close_computer",
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


from helpers.errors import classify_api_error as _classify_api_error, emit_api_diagnostic as _emit_api_diagnostic


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


class NotificationAckRequest(BaseModel):
    # None clears everything unread.
    id: typing.Optional[int] = None


# Wall-clock backstop for one web turn, mirroring _TURN_TIMEOUT_SECONDS in
# modules/employer.py — without it a stuck tool loop held agent_lock (and so
# every other turn, voice included) until the process was restarted.
_WEB_TURN_TIMEOUT_SECONDS = 120.0


def _run_web_turn(
    message: str,
    on_text: typing.Optional[typing.Callable[[str], None]] = None,
) -> typing.Any:
    """Run one agent turn for a web client. Shared by POST /api/chat and the
    WebSocket chat path so both get the same cancel and timeout behaviour."""
    import threading

    from helpers.agent import run_agent
    from helpers.bootstrap import get_ai_client
    from helpers.conversation import Conversation
    from helpers.decorators import agent_lock, set_agent_active
    from helpers.events import clear_cancel, session_cancel
    from modules.ai import build_agent_system_prompt
    from modules.employer import MAX_AGENT_STEPS

    ai_client = get_ai_client()
    system_prompt = build_agent_system_prompt()
    all_jobs = ServiceRegistry.get_all_jobs()

    timed_out = threading.Event()
    timer = threading.Timer(_WEB_TURN_TIMEOUT_SECONDS, timed_out.set)
    timer.daemon = True

    class _TurnCancel:
        @staticmethod
        def is_set() -> bool:
            return session_cancel.is_set() or timed_out.is_set()

    with agent_lock:
        # Inside the lock: a cancel raised against a previous turn must not
        # abort this one, but clearing it earlier could cancel a voice turn
        # that is still running.
        clear_cancel()
        set_agent_active(True)
        timer.start()
        try:
            return run_agent(
                client=ai_client,
                user_input=message,
                available_jobs=all_jobs,
                system_instructions=system_prompt,
                history=Conversation.get_messages(),
                max_steps=MAX_AGENT_STEPS,
                on_text=on_text,
                cancel_event=_TurnCancel(),
            )
        finally:
            timer.cancel()
            set_agent_active(False)


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
        from helpers.audio import _MAX_CAPTURE_SECONDS

        return {
            "assistant": {
                "name": Config.get("assistant.name", "Wony"),
                "language": Config.get("assistant.language", "en"),
            },
            "voice": {
                "stt": {
                    "silence_ms": int(Config.get("voice.stt.silence_ms", 700)),
                    "start_timeout": int(Config.get("voice.stt.start_timeout", 4)),
                    "max_seconds": int(_MAX_CAPTURE_SECONDS),
                },
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

        return {
            "provider": provider,
            "model": model_name,
            "modules": modules_out,
            "compute": compute,
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
        lamps called 'Lamp'. The UI already knows which one was clicked.
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
                req.entity_id, req.action, req.brightness_percent
            )
        except Exception as e:
            logger.log_error(str(e), "web_device_control")
            raise HTTPException(status_code=502, detail=str(e))
        return {"ok": ok, "text": text}

    @app.get("/api/notifications")
    def list_notifications(include_acknowledged: bool = False, limit: int = 50):
        from helpers.memory_db import all_notifications

        return {
            "notifications": all_notifications(
                include_acknowledged=include_acknowledged, limit=min(limit, 200)
            )
        }

    @app.post("/api/notifications/ack")
    def ack_notifications(req: NotificationAckRequest) -> typing.Dict[str, typing.Any]:
        """Clear one notification, or every unread one when no id is given."""
        from helpers.memory_db import (
            acknowledge_all_notifications,
            acknowledge_notification,
        )

        if req.id is None:
            return {"cleared": acknowledge_all_notifications()}
        return {"cleared": 1 if acknowledge_notification(req.id) else 0}

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
            # agent_lock guards the per-turn tool-outcome ledger (see scheduler._run_action)
            from helpers.decorators import agent_lock

            with agent_lock:
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
        from helpers.logger import logger

        if not req.message or not req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        try:
            result = _run_web_turn(req.message)
            safe_calls = _sanitize_calls(result.calls)
            turn_id = Conversation.record_turn(
                req.message, result.text, calls=safe_calls
            )
            return {"id": turn_id, "text": result.text, "calls": safe_calls}
        except Exception as e:
            logger.log_error(str(e), "web_chat")
            classified = _classify_api_error(e)
            if classified:
                user_msg, hint = classified
                _emit_api_diagnostic(user_msg, hint)
                raise HTTPException(status_code=503, detail=user_msg)
            raise HTTPException(status_code=500, detail=str(e))


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

    @app.post("/api/ack")
    async def play_ack() -> typing.Dict[str, bool]:
        """Play the 'Yes?' acknowledgement chime through PC speakers."""
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
            import tempfile

            import numpy as np

            # Decode via av (already bundled with faster-whisper)
            import av

            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                frames_by_rate: typing.Dict[int, typing.List[np.ndarray]] = {}
                with av.open(tmp_path) as container:
                    for frame in container.decode(audio=0):
                        raw = frame.to_ndarray()
                        channels = len(frame.layout.channels) if frame.layout else 1
                        if np.issubdtype(raw.dtype, np.integer):
                            raw = raw.astype(np.float32) / float(np.iinfo(raw.dtype).max)
                        else:
                            raw = raw.astype(np.float32)
                        if raw.ndim > 1 and raw.shape[0] == channels and channels > 1:
                            mono = raw.mean(axis=0)  # planar: (channels, samples)
                        elif raw.ndim > 1:
                            flat = raw.reshape(-1)
                            mono = flat.reshape(-1, channels).mean(axis=1) if channels > 1 else flat
                        else:
                            mono = raw
                        frames_by_rate.setdefault(int(frame.sample_rate), []).append(mono)
                os.unlink(tmp_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            if not frames_by_rate:
                return {"text": ""}

            # Resample each same-rate run to 16k, then concatenate. Using the
            # frame's actual sample_rate (instead of assuming 48000) also
            # fixes the silent failure mode where a browser encoding at a
            # different rate got mislabeled and fed straight to Whisper.
            from helpers import mic
            chunks = [
                mic.to_16k_mono_f32(np.concatenate(parts), rate)
                for rate, parts in frames_by_rate.items()
            ]
            audio = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)

            if not np.all(np.isfinite(audio)):
                return {
                    "text": "",
                    "warning": "Your browser microphone captured invalid audio — check the browser's mic permission and Windows input device.",
                }
            rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
            if rms < 1e-4:
                return {
                    "text": "",
                    "warning": "Your browser microphone captured silence — check the browser's mic permission and Windows input device.",
                }

            from helpers.recognizer import transcribe
            return {"text": transcribe(audio)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"STT failed: {e}")

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
            from helpers.conversation import Conversation
            from helpers.logger import logger

            try:
                result = _run_web_turn(message, on_text=lambda c: q.put(("delta", c)))

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
                classified = _classify_api_error(e)
                if classified:
                    user_msg, hint = classified
                    _emit_api_diagnostic(user_msg, hint)
                    q.put(("error", user_msg))
                else:
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

    _dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")

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
                return FileResponse(index)
            return JSONResponse({"detail": "Not found"}, status_code=404)

    return app
