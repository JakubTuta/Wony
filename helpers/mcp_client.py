"""
MCP client adapter.

Maintains one persistent asyncio event loop on a daemon thread so the
synchronous agent loop can call async MCP SDK operations via
asyncio.run_coroutine_threadsafe.

One MCPServerSession per connected server holds the ClientSession alive in a
background coroutine. Tool wrappers are registered/unregistered in
ServiceRegistry dynamically — no restart needed.
"""
import asyncio
import json
import threading
import typing

from helpers.logger import logger

# ------------------------------------------------------------------ background loop

_loop: typing.Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or not _loop.is_running():
            new_loop = asyncio.new_event_loop()
            t = threading.Thread(target=new_loop.run_forever, daemon=True, name="mcp-loop")
            t.start()
            _loop = new_loop
    return _loop


def _run_sync(coro: typing.Coroutine, timeout: float = 30.0) -> typing.Any:
    """Run a coroutine on the background loop and return its result synchronously."""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=timeout)


# ------------------------------------------------------------------ server session

class MCPServerSession:
    """Holds a live MCP ClientSession open in the background loop."""

    def __init__(self, name: str, record: typing.Dict) -> None:
        self.name = name
        self.record = record
        self._session: typing.Any = None
        self._tools: typing.List[typing.Dict] = []
        self._ready = threading.Event()
        self._error: typing.Optional[Exception] = None
        self._stop_event: typing.Optional[asyncio.Event] = None

    # ---------------------------------------------------------------- public sync API

    def connect(self, timeout: float = 20.0) -> None:
        """Start session in background loop. Blocks until ready or raises."""
        asyncio.run_coroutine_threadsafe(self._run(), _get_loop())
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError(f"MCP server '{self.name}' did not connect within {timeout:.0f}s.")
        if self._error:
            raise self._error

    def disconnect(self) -> None:
        if self._stop_event is not None:
            _get_loop().call_soon_threadsafe(self._stop_event.set)

    def list_tools(self) -> typing.List[typing.Dict]:
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments: typing.Dict) -> str:
        return _run_sync(self._call_tool_async(tool_name, arguments))

    # ---------------------------------------------------------------- async internals

    async def _run(self) -> None:
        transport = self.record.get("transport", "stdio")
        try:
            if transport == "stdio":
                await self._run_stdio()
            elif transport in ("sse", "http"):
                await self._run_sse()
            else:
                raise ValueError(f"Unknown MCP transport: '{transport}'")
        except Exception as exc:
            self._error = exc
            self._ready.set()

    async def _run_stdio(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        cmd = self.record.get("command") or ""
        args: typing.List[str] = json.loads(self.record.get("args") or "[]")
        env_raw = self.record.get("env") or "{}"
        env: typing.Optional[typing.Dict[str, str]] = json.loads(env_raw) or None

        params = StdioServerParameters(command=cmd, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await self._session_ready(session)

    async def _run_sse(self) -> None:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = self.record.get("url") or ""
        headers: typing.Dict[str, str] = {}
        tokens_raw = self.record.get("oauth_tokens")
        if tokens_raw:
            tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
            if tokens.get("access_token"):
                headers["Authorization"] = f"Bearer {tokens['access_token']}"

        async with sse_client(url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await self._session_ready(session)

    async def _session_ready(self, session: typing.Any) -> None:
        await session.initialize()
        result = await session.list_tools()
        self._tools = [
            {
                "name": t.name,
                "description": t.description or t.name,
                "inputSchema": (
                    t.inputSchema.model_dump()
                    if hasattr(t.inputSchema, "model_dump")
                    else dict(t.inputSchema)
                ) if t.inputSchema else {"type": "object", "properties": {}},
            }
            for t in result.tools
        ]
        self._session = session
        self._stop_event = asyncio.Event()
        self._ready.set()
        await self._stop_event.wait()  # keep session alive until disconnect()

    async def _call_tool_async(self, tool_name: str, arguments: typing.Dict) -> str:
        if self._session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected.")
        result = await self._session.call_tool(tool_name, arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else "Done."


# ------------------------------------------------------------------ manager

_sessions: typing.Dict[str, MCPServerSession] = {}
_sessions_lock = threading.Lock()


def connect_server(record: typing.Dict) -> MCPServerSession:
    """Connect to an MCP server and register its tools. Returns the session."""
    name = record["name"]
    with _sessions_lock:
        if name in _sessions:
            return _sessions[name]

    session = MCPServerSession(name, record)
    session.connect()

    with _sessions_lock:
        _sessions[name] = session

    _register_tools(session)
    return session


def disconnect_server(name: str) -> None:
    """Disconnect a server and unregister its tools."""
    with _sessions_lock:
        session = _sessions.pop(name, None)
    if session:
        session.disconnect()
    _unregister_tools(name)


def get_session(name: str) -> typing.Optional[MCPServerSession]:
    with _sessions_lock:
        return _sessions.get(name)


def all_connected() -> typing.List[str]:
    with _sessions_lock:
        return list(_sessions.keys())


def reconnect_enabled_servers() -> None:
    """Called at startup: reconnect all enabled servers from the DB."""
    try:
        from helpers.memory_db import all_mcp_servers
        records = all_mcp_servers(enabled_only=True)
    except Exception as exc:
        logger.log_error(str(exc), "mcp.reconnect_enabled")
        return

    for record in records:
        try:
            connect_server(record)
            logger.log_system_event("mcp_reconnected", record["name"])
        except Exception as exc:
            _mark_error(record["name"], str(exc))
            logger.log_error(str(exc), f"mcp.reconnect.{record['name']}")


# ------------------------------------------------------------------ registry helpers

def _register_tools(session: MCPServerSession) -> None:
    from helpers.registry import ServiceRegistry

    module_name = f"mcp:{session.name}"
    for tool in session.list_tools():
        tool_name = tool["name"]
        description = tool.get("description") or tool_name
        input_schema = tool.get("inputSchema") or {"type": "object", "properties": {}}

        def _make_wrapper(
            sess: MCPServerSession,
            tname: str,
            desc: str,
            schema: typing.Dict,
        ) -> typing.Callable:
            def wrapper(**kwargs: typing.Any) -> str:
                return sess.call_tool(tname, kwargs)
            wrapper.__name__ = tname
            wrapper.__doc__ = desc
            wrapper._tool_schema = schema  # type: ignore[attr-defined]
            return wrapper

        fn = _make_wrapper(session, tool_name, description, input_schema)
        ServiceRegistry._jobs[tool_name] = fn
        ServiceRegistry._job_modules[tool_name] = module_name
        ServiceRegistry._job_summaries[tool_name] = description[:80]

    ServiceRegistry._module_status[module_name] = ("enabled", "")
    logger.log_system_event(
        "mcp_tools_registered",
        f"{session.name}: {len(session.list_tools())} tool(s)",
    )


def _unregister_tools(server_name: str) -> None:
    from helpers.registry import ServiceRegistry

    module_name = f"mcp:{server_name}"
    to_remove = [k for k, v in ServiceRegistry._job_modules.items() if v == module_name]
    for k in to_remove:
        ServiceRegistry._jobs.pop(k, None)
        ServiceRegistry._job_modules.pop(k, None)
        ServiceRegistry._job_summaries.pop(k, None)
    ServiceRegistry._module_status.pop(module_name, None)


def _mark_error(server_name: str, reason: str) -> None:
    from helpers.registry import ServiceRegistry
    ServiceRegistry._module_status[f"mcp:{server_name}"] = ("error", reason)
