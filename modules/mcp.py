"""
MCP server management jobs.

All CRUD operations are callable from chat — no config editing needed.
State is persisted in the mcp_servers table in wony.db; tool wrappers are
registered/unregistered in ServiceRegistry dynamically without restart.
"""
import json
import typing

from helpers.decorators import capture_response
from helpers.registry import register_job


def _client():
    from helpers import mcp_client
    return mcp_client


@register_job(module_name="mcp", summary="List all MCP server connections and their status")
@capture_response
def list_mcp_servers() -> str:
    """
    [MCP JOB] Lists all configured MCP server connections and their current status.

    Use this job when the user wants to:
    - See all configured MCP servers
    - Check which servers are connected
    - View connection status of integrations

    Keywords: list mcp servers, mcp status, show connections, mcp connections, integrations

    Args:
        None

    Returns:
        str: Table of servers with name, transport, address, and status.
    """
    from helpers.memory_db import all_mcp_servers

    records = all_mcp_servers()
    connected = set(_client().all_connected())

    if not records:
        return "No MCP servers configured. Use add_mcp_server to add one."

    lines = [f"{len(records)} MCP server(s) configured:"]
    for r in records:
        name = r["name"]
        transport = r["transport"]
        enabled = bool(r["enabled"])
        if name in connected:
            status = "connected"
        elif not enabled:
            status = "disabled"
        else:
            status = "disconnected"
        addr = r.get("url") or r.get("command") or ""
        lines.append(f"  [{name}] {transport} {addr!r} — {status}")
    return "\n".join(lines)


@register_job(module_name="mcp", summary="Add a new MCP server connection")
@capture_response
def add_mcp_server(
    name: str,
    transport: str = "stdio",
    command: str = "",
    url: str = "",
    args: str = "[]",
    env: str = "{}",
    auto_connect: bool = True,
) -> str:
    """
    [MCP JOB] Adds a new MCP server configuration and optionally connects to it.

    Use this job when the user wants to:
    - Add a new MCP server integration
    - Register a new tool provider
    - Connect to an external service via MCP

    Keywords: add mcp server, new mcp, add integration, register mcp, add tool server

    Args:
        name (str): Unique server name (e.g. "notion", "github"). (required)
        transport (str): Connection type: "stdio" (default) or "sse"/"http".
        command (str): Executable command for stdio transport (e.g. "npx @notionhq/mcp").
        url (str): Base URL for sse/http transport.
        args (str): JSON array of command arguments for stdio (e.g. '["--token", "xyz"]').
        env (str): JSON object of extra environment variables (e.g. '{"API_KEY": "xyz"}').
        auto_connect (bool): Connect immediately after adding (default true).

    Returns:
        str: Confirmation with number of available tools, or error message.
    """
    from helpers.memory_db import get_mcp_server, upsert_mcp_server

    if not name:
        return "Error: name is required."

    if get_mcp_server(name):
        return f"Server '{name}' already exists. Use edit_mcp_server to modify it."

    # Validate JSON fields
    try:
        json.loads(args)
    except json.JSONDecodeError:
        return f"Error: 'args' must be a valid JSON array (e.g. '[\"--flag\"]'). Got: {args!r}"
    try:
        json.loads(env)
    except json.JSONDecodeError:
        return f"Error: 'env' must be a valid JSON object (e.g. '{{\"KEY\": \"val\"}}')."

    record: typing.Dict = {
        "name": name,
        "transport": transport,
        "command": command or None,
        "args": args,
        "env": env,
        "url": url or None,
        "oauth_tokens": None,
        "enabled": 1,
    }
    upsert_mcp_server(record)

    if auto_connect:
        try:
            _client().connect_server(record)
            tools = _client().get_session(name).list_tools()
            tool_names = ", ".join(t["name"] for t in tools[:5])
            suffix = "…" if len(tools) > 5 else ""
            return (
                f"Added and connected '{name}'. "
                f"{len(tools)} tool(s) available: {tool_names}{suffix}."
            )
        except Exception as exc:
            return f"Added '{name}' but connection failed: {exc}"

    return f"Added MCP server '{name}' (not connected — use connect_mcp_server to connect)."


@register_job(module_name="mcp", summary="Connect to a configured MCP server")
@capture_response
def connect_mcp_server(name: str) -> str:
    """
    [MCP JOB] Connects to a previously configured MCP server and registers its tools.

    Use this job when the user wants to:
    - Connect to an MCP server that was added but not yet connected
    - Reconnect to a disconnected server

    Keywords: connect mcp, connect server, reconnect mcp, start mcp connection

    Args:
        name (str): The server name to connect to. (required)

    Returns:
        str: Confirmation with available tool count, or error.
    """
    from helpers.memory_db import get_mcp_server

    if not name:
        return "Error: server name is required."

    record = get_mcp_server(name)
    if not record:
        return f"No server named '{name}'. Use add_mcp_server first."

    if name in _client().all_connected():
        return f"Server '{name}' is already connected."

    try:
        _client().connect_server(record)
        tools = _client().get_session(name).list_tools()
        tool_names = ", ".join(t["name"] for t in tools[:5])
        suffix = "…" if len(tools) > 5 else ""
        return f"Connected to '{name}'. {len(tools)} tool(s): {tool_names}{suffix}."
    except Exception as exc:
        return f"Failed to connect to '{name}': {exc}"


@register_job(module_name="mcp", summary="Disconnect from an MCP server")
@capture_response
def disconnect_mcp_server(name: str) -> str:
    """
    [MCP JOB] Disconnects from an active MCP server session and unregisters its tools.

    Use this job when the user wants to:
    - Disconnect from an MCP server
    - Remove an active tool provider session (without deleting the config)

    Keywords: disconnect mcp, stop mcp, pause mcp server

    Args:
        name (str): The server name to disconnect. (required)

    Returns:
        str: Confirmation or error.
    """
    if not name:
        return "Error: server name is required."

    if name not in _client().all_connected():
        return f"Server '{name}' is not currently connected."

    _client().disconnect_server(name)
    return f"Disconnected from '{name}'."


@register_job(module_name="mcp", summary="Edit an existing MCP server configuration")
@capture_response
def edit_mcp_server(
    name: str,
    transport: str = "",
    command: str = "",
    url: str = "",
    args: str = "",
    env: str = "",
    enabled: str = "",
) -> str:
    """
    [MCP JOB] Edits an existing MCP server's configuration (transport, command, URL, env, etc.).
    Reconnect manually after editing if the server was already connected.

    Use this job when the user wants to:
    - Change the URL or command of an MCP server
    - Update auth credentials or environment variables
    - Enable or disable a server

    Keywords: edit mcp server, update mcp, change mcp config, modify mcp server

    Args:
        name (str): The server name to edit. (required)
        transport (str): New transport type (leave empty to keep current).
        command (str): New command for stdio transport.
        url (str): New URL for sse/http transport.
        args (str): New JSON array of command arguments.
        env (str): New JSON object of environment variables.
        enabled (str): "true" or "false" to enable/disable.

    Returns:
        str: Confirmation or error.
    """
    from helpers.memory_db import get_mcp_server, upsert_mcp_server

    if not name:
        return "Error: server name is required."

    record = get_mcp_server(name)
    if not record:
        return f"No server named '{name}'."

    if transport:
        record["transport"] = transport
    if command:
        record["command"] = command
    if url:
        record["url"] = url
    if args:
        try:
            json.loads(args)
        except json.JSONDecodeError:
            return f"Error: 'args' must be a valid JSON array."
        record["args"] = args
    if env:
        try:
            json.loads(env)
        except json.JSONDecodeError:
            return f"Error: 'env' must be a valid JSON object."
        record["env"] = env
    if enabled:
        record["enabled"] = 1 if enabled.lower() in ("true", "1", "yes") else 0

    upsert_mcp_server(record)

    was_connected = name in _client().all_connected()
    note = " Reconnect with connect_mcp_server to apply changes." if was_connected else ""
    return f"Updated server '{name}'.{note}"


@register_job(module_name="mcp", summary="Remove an MCP server and its stored credentials")
@capture_response
def remove_mcp_server(name: str) -> str:
    """
    [MCP JOB] Permanently removes an MCP server configuration and its stored tokens.
    Disconnects first if currently active.

    Use this job when the user wants to:
    - Remove an MCP server integration
    - Delete a connection and its credentials
    - Clean up an unused server

    Keywords: remove mcp server, delete mcp, unregister mcp, remove integration

    Args:
        name (str): The server name to remove. (required)

    Returns:
        str: Confirmation or error.
    """
    from helpers.memory_db import get_mcp_server, delete_mcp_server

    if not name:
        return "Error: server name is required."

    if not get_mcp_server(name):
        return f"No server named '{name}'."

    if name in _client().all_connected():
        _client().disconnect_server(name)

    delete_mcp_server(name)
    return f"Removed MCP server '{name}'."
