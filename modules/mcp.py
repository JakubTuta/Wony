"""
MCP server management jobs.

State is persisted in the mcp_servers table in wony.db; tool wrappers are
registered/unregistered in ServiceRegistry dynamically without a restart.
"""
import json

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement

_MCP_REQUIREMENT = Requirement(
    pip_modules=["mcp"],
    setup_hint="pip install -r requirements/mcp.txt",
)


def _client():
    from helpers import mcp_client

    return mcp_client


def _tool_summary(name: str) -> str:
    tools = _client().get_session(name).list_tools()
    listed = ", ".join(t["name"] for t in tools[:5])
    return f"{len(tools)} tool(s): {listed}{'…' if len(tools) > 5 else ''}"


def _valid_json(value: str, shape: type) -> bool:
    try:
        return isinstance(json.loads(value), shape)
    except (json.JSONDecodeError, ValueError):
        return False


@register_job(
    module_name="mcp",
    requires=_MCP_REQUIREMENT,
    summary="List MCP server connections and their status",
)
@capture_response
def list_mcp_servers() -> str:
    """
    [MCP JOB] Lists every configured MCP server connection and whether it is
    currently connected.

    Returns:
        str: Each server with its transport, address, and status.
    """
    from helpers.memory_db import all_mcp_servers

    records = all_mcp_servers()
    connected = set(_client().all_connected())

    if not records:
        return "No MCP servers configured. Use manage_mcp_server to add one."

    lines = [f"{len(records)} MCP server(s) configured:"]
    for record in records:
        name = record["name"]
        if name in connected:
            status = "connected"
        elif not bool(record["enabled"]):
            status = "disabled"
        else:
            status = "disconnected"
        address = record.get("url") or record.get("command") or ""
        lines.append(f"  [{name}] {record['transport']} {address!r} — {status}")
    return "\n".join(lines)


@register_job(
    module_name="mcp",
    requires=_MCP_REQUIREMENT,
    summary="Add, edit, remove, connect or disconnect an MCP server",
)
@capture_response
def manage_mcp_server(
    action: str = "add",
    name: str = "",
    transport: str = "stdio",
    command: str = "",
    url: str = "",
    args: str = "",
    env: str = "",
    enabled: str = "",
) -> str:
    """
    [MCP JOB] Adds, edits, removes, connects or disconnects one MCP server — an
    external tool server that gives Wony extra abilities. Adding connects straight
    away. Editing keeps any field left empty as it was.

    Args:
        action (str): "add" (the default), "edit", "remove", "connect" or "disconnect".
        name (str): The server name, e.g. "notion", "github". (required)
        transport (str): "stdio" (the default) or "sse"/"http".
        command (str): Executable command for stdio transport, e.g. "npx @notionhq/mcp".
        args (str): JSON array of command arguments, e.g. '["--token", "xyz"]'.
        url (str): Base URL for sse/http transport.
        env (str): JSON object of extra environment variables, e.g. '{"API_KEY": "xyz"}'.
        enabled (str): "true" or "false" to switch a server on or off when editing.

    Returns:
        str: Confirmation of what changed, or the reason it could not be done.
    """
    from helpers.memory_db import delete_mcp_server, get_mcp_server, upsert_mcp_server

    wanted = (action or "add").strip().lower()
    if not name:
        return "Error: server name is required."

    record = get_mcp_server(name)
    connected = _client().all_connected()

    for field, value, shape in (("args", args, list), ("env", env, dict)):
        if value and not _valid_json(value, shape):
            kind = "array" if shape is list else "object"
            return f"Error: '{field}' must be a JSON {kind}. Got: {value!r}"

    if wanted == "add":
        if record:
            return f"Server '{name}' already exists. Use action 'edit' to change it."
        upsert_mcp_server({
            "name": name,
            "transport": transport,
            "command": command or None,
            "args": args or "[]",
            "env": env or "{}",
            "url": url or None,
            "oauth_tokens": None,
            "enabled": 1,
        })
        try:
            _client().connect_server(get_mcp_server(name))
        except Exception as exc:
            return f"Added '{name}' but connecting failed: {exc}"
        return f"Added and connected '{name}'. {_tool_summary(name)}."

    if not record:
        return f"No server named '{name}'. Use action 'add' to create it."

    if wanted == "edit":
        if transport and transport != "stdio":
            record["transport"] = transport
        if command:
            record["command"] = command
        if url:
            record["url"] = url
        if args:
            record["args"] = args
        if env:
            record["env"] = env
        if enabled:
            record["enabled"] = 1 if enabled.strip().lower() in ("true", "1", "yes") else 0
        upsert_mcp_server(record)
        note = " Connect again to apply the change." if name in connected else ""
        return f"Updated server '{name}'.{note}"

    if wanted in ("remove", "delete"):
        if name in connected:
            _client().disconnect_server(name)
        delete_mcp_server(name)
        return f"Removed MCP server '{name}'."

    if wanted == "connect":
        if name in connected:
            return f"Server '{name}' is already connected."
        try:
            _client().connect_server(record)
        except Exception as exc:
            return f"Failed to connect to '{name}': {exc}"
        return f"Connected to '{name}'. {_tool_summary(name)}."

    if wanted == "disconnect":
        if name not in connected:
            return f"Server '{name}' is not connected."
        _client().disconnect_server(name)
        return f"Disconnected from '{name}'."

    return f"Unknown action '{action}'. Use add, edit, remove, connect or disconnect."
