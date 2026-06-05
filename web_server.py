"""
FastAPI web server for the Wony assistant.

Startup order mirrors assistant.py exactly: Config.load() must precede all module
imports so decorator-based job registration uses the correct config gates.
"""
import atexit
import json
import signal
import sys
import typing

# ── 1. Config first (before any module imports) ──────────────────────────────
from helpers.config import Config
Config.load()

# ── 2. Cache + audio/local flags ─────────────────────────────────────────────
from helpers.cache import Cache
Cache.load_values()
Cache.set_audio(False)   # web mode: never TTS
Cache.set_local(bool(Config.get("ai.local", False)))

# ── 3. Secrets ────────────────────────────────────────────────────────────────
import dotenv
dotenv.load_dotenv()

# ── 4. Preflight ──────────────────────────────────────────────────────────────
from helpers.model import describe_readiness
ai_ok, ai_msg = describe_readiness()
if not ai_ok:
    print(f"\nCannot start: AI provider not ready.\n{ai_msg}\n")
    sys.exit(1)

# ── 5. Module discovery (registers all jobs) ─────────────────────────────────
from modules.employer import Employer   # noqa: F401  triggers discover_services()

# ── 6. Shared AI client ───────────────────────────────────────────────────────
from helpers.registry import ServiceRegistry
_ai_instance = ServiceRegistry.get_service_instance("ai")
if _ai_instance is None:
    print("Cannot start: AI service not registered.")
    sys.exit(1)
ai_client = _ai_instance.client

# ── 7. Shutdown hooks (mirrors assistant.py) ─────────────────────────────────
def _shutdown() -> None:
    try:
        from helpers.jobs import BackgroundJobs
        BackgroundJobs.stop_all()
    except Exception:
        pass
    try:
        sched = ServiceRegistry.get_service_instance("scheduler")
        if sched is not None and hasattr(sched, "_sched"):
            sched._sched.shutdown(wait=False)
    except Exception:
        pass
    try:
        from helpers.memory_db import close as db_close
        db_close()
    except Exception:
        pass

atexit.register(_shutdown)

# ── Seed in-memory conversation from DB (so AI has recent context on startup) ─
try:
    from helpers.memory_db import recent_turns as _recent_turns
    from helpers.conversation import Conversation as _Conv
    from helpers.config import Config as _Cfg
    _max = int(_Cfg.get("ai.history.max_turns", 5))
    for _t in _recent_turns(_max):
        _Conv._turns.append({"user": _t["user_text"], "assistant": _t["assistant_text"]})
    _Conv._last_activity = __import__("time").time()
except Exception:
    pass

def _signal_handler(signum: int, frame: object) -> None:
    print(f"\nReceived signal {signum}, shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, _signal_handler)

# ── FastAPI app ───────────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

app = FastAPI(title="Wony Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Destructive job list ──────────────────────────────────────────────────────
_DEFAULT_DESTRUCTIVE = {
    "exit",
    "close_computer",
    "stop_active_jobs",
    "cancel_timers",
    "send_email",
    "reply_to_email",
    "mark_as_read",
    "create_event",
    "edit_event",
    "delete_event",
}

def _get_destructive_set() -> typing.Set[str]:
    from_config = Config.get("server.destructive_jobs", None)
    if from_config and isinstance(from_config, list):
        return set(from_config)
    return _DEFAULT_DESTRUCTIVE


# ── Arg coercion ─────────────────────────────────────────────────────────────
def _coerce_args(
    func: typing.Callable,
    raw: typing.Dict[str, typing.Any],
) -> typing.Dict[str, typing.Any]:
    """Coerce string values from the frontend into the types the function expects."""
    from helpers.tools import _parse_signature
    _, properties, _ = _parse_signature(func)

    coerced: typing.Dict[str, typing.Any] = {}
    for key, value in raw.items():
        if value == "" or value is None:
            continue  # skip empty optional fields
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
                        coerced[key] = [v.strip() for v in str(value).split(",") if v.strip()]
            elif prop_type == "object":
                if isinstance(value, dict):
                    coerced[key] = value
                else:
                    coerced[key] = json.loads(value)
            else:
                coerced[key] = str(value)
        except (ValueError, TypeError):
            coerced[key] = value  # pass through unchanged; let the function raise

    return coerced


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
    # model_info[1] is the API key, not the model name — get name from config
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
        modules_out[name] = {"status": st, "reason": reason, "hint": hints.get(name, "")}

    return {"provider": provider, "model": model_name, "modules": modules_out}


@app.get("/api/jobs")
def list_jobs() -> typing.Dict[str, typing.Any]:
    from helpers.tools import _parse_signature
    all_jobs = ServiceRegistry.get_all_jobs()
    job_modules = ServiceRegistry.get_job_modules()
    job_summaries = ServiceRegistry.get_job_summaries()
    destructive = _get_destructive_set()

    jobs_out = []
    for name, func in all_jobs.items():
        try:
            description, properties, required = _parse_signature(func)
        except Exception:
            description, properties, required = "", {}, []

        jobs_out.append({
            "name": name,
            "module": job_modules.get(name, ""),
            "summary": job_summaries.get(name, ""),
            "description": description,
            "destructive": name in destructive,
            "parameters": {
                "properties": properties,
                "required": required,
            },
        })

    return {"jobs": jobs_out}


class InvokeRequest(BaseModel):
    name: str
    args: typing.Dict[str, typing.Any] = {}


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
        raise HTTPException(status_code=422, detail=f"Argument coercion failed: {e}")

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


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest) -> typing.Dict[str, typing.Any]:
    from helpers.agent import run_agent
    from helpers.conversation import Conversation
    from helpers.decorators import set_agent_active
    from modules.ai import build_agent_system_prompt

    system_prompt = build_agent_system_prompt()
    history = Conversation.get_messages()
    max_steps = int(Config.get("ai.agent.max_steps", 5))
    all_jobs = ServiceRegistry.get_all_jobs()

    set_agent_active(True)
    try:
        result = run_agent(
            client=ai_client,
            user_input=req.message,
            available_jobs=all_jobs,
            system_instructions=system_prompt,
            history=history,
            max_steps=max_steps,
        )
    finally:
        set_agent_active(False)

    Conversation.record_turn(req.message, result.text)
    return {"text": result.text, "calls": result.calls}


@app.post("/api/chat/clear")
def clear_chat() -> typing.Dict[str, str]:
    from helpers.conversation import Conversation
    Conversation.clear()
    return {"status": "cleared"}


@app.get("/api/chat/history")
def chat_history(limit: int = 50) -> typing.Dict[str, typing.Any]:
    from helpers.memory_db import recent_turns
    turns = recent_turns(min(limit, 200))
    return {
        "turns": [
            {"user": t["user_text"], "assistant": t["assistant_text"], "ts": t["ts"]}
            for t in turns
        ]
    }


# ── Static files (built React app) ───────────────────────────────────────────
_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")

if os.path.isdir(_DIST):
    # Serve /assets/* as static files
    _ASSETS = os.path.join(_DIST, "assets")
    if os.path.isdir(_ASSETS):
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    # SPA fallback via 404 handler — avoids Starlette mount intercepting /api/* routes
    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: HTTPException) -> FileResponse | JSONResponse:
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        index = os.path.join(_DIST, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return JSONResponse({"detail": "Not found"}, status_code=404)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    print(f"\nWony Web Server → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port)
