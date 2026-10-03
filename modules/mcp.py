"""
MCP server management jobs.

State is persisted in the mcp_servers table in wony.db; tool wrappers are
registered/unregistered in ServiceRegistry dynamically without a restart.
"""
import json
import typing

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement

_MCP_REQUIREMENT = Requirement(
    pip_modules=["mcp"],
    setup_hint="Run install.bat again and tick MCP client.",
)


def _client():
    from helpers import mcp_client

    return mcp_client


def _tool_summary(name: str) -> str:
    tools = _client().get_session(name).list_tools()
    listed = ", ".join(t["name"] for t in tools[:5])
    return f"{len(tools)} tool(s): {listed}{'…' if len(tools) > 5 else ''}"


def _install_allowed() -> bool:
    from helpers.config import Config

    return bool(Config.module_settings("mcp").get("allow_install", False))


def _spawn_summary(transport: str, command: str, args: str, url: str) -> str:
    """The command line (or address) a connect would actually use."""
    if (transport or "stdio") != "stdio":
        return url or "(no url)"
    try:
        parsed = json.loads(args or "[]")
    except (json.JSONDecodeError, ValueError):
        parsed = []
    parts = [command or "(no command)"] + [str(a) for a in parsed]
    return " ".join(parts)


def _install_refusal(action: str, what: str) -> str:
    """What the gate says instead of spawning the server.

    Adding, editing or connecting an MCP server starts a process of the user's
    choosing with the user's privileges, so it is gated like every other action
    that changes something outside Wony. Echoing the command back means the
    answer is still useful: the user can read it and run it themselves.
    """
    from helpers.settings import where

    return (
        f"MCP server '{action}' is switched off — it would have started: {what}\n"
        f"Turn on {where('modules.mcp.allow_install')} to allow it."
    )


def _valid_json(value: str, shape: type) -> bool:
    try:
        return isinstance(json.loads(value), shape)
    except (json.JSONDecodeError, ValueError):
        return False


@register_job(
    module_name="mcp",
    requires=_MCP_REQUIREMENT,
    summary="List, add, edit, remove, connect or disconnect MCP servers",
    confirms={"add", "edit", "remove", "delete", "connect", "disconnect"},
)
@capture_response
def manage_mcp_server(
    action: typing.Literal["list", "add", "edit", "remove", "connect", "disconnect"] = "list",
    name: str = "",
    transport: typing.Literal["", "stdio", "sse", "http"] = "",
    command: str = "",
    url: str = "",
    args: str = "",
    env: str = "",
    enabled: str = "",
) -> str:
    """
    [MCP JOB] Lists the MCP servers — external tool servers that give Wony extra
    abilities — and whether each is connected, or adds, edits, removes, connects or
    disconnects one. Adding connects straight away. Editing keeps any field left
    empty as it was.

    Args:
        action (str): "list" (the default), "add", "edit", "remove", "connect" or
            "disconnect".
        name (str): The server name, e.g. "notion", "github". (required except for list)
        transport (str): "stdio" (the default), "sse" or "http".
        command (str): Executable command for stdio transport, e.g. "npx @notionhq/mcp".
        args (str): JSON array of command arguments, e.g. '["--token", "xyz"]'.
        url (str): Base URL for sse/http transport.
        env (str): JSON object of extra environment variables, e.g. '{"API_KEY": "xyz"}'.
        enabled (str): "true" or "false" to switch a server on or off when editing.

    Returns:
        str: Confirmation of what changed, or the reason it could not be done.
    """
    from helpers.memory_db import delete_mcp_server, get_mcp_server, upsert_mcp_server

    wanted = (action or "list").strip().lower()
    if wanted == "list":
        return _server_list()
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
        if not _install_allowed():
            return _install_refusal("add", _spawn_summary(transport, command, args, url))
        upsert_mcp_server({
            "name": name,
            "transport": transport or "stdio",
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
        # Editing what a server runs, or switching a server back on, both end in
        # a spawned process — the same thing 'add' is gated for. Turning a server
        # off is the safe direction and stays ungated.
        enabling = enabled.strip().lower() in ("true", "1", "yes")
        if (command or args or env or url or enabling) and not _install_allowed():
            return _install_refusal(
                "edit",
                _spawn_summary(
                    transport or record.get("transport", "stdio"),
                    command or record.get("command") or "",
                    args or record.get("args") or "",
                    url or record.get("url") or "",
                ),
            )
        if transport:
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
        if not _install_allowed():
            return _install_refusal(
                "connect",
                _spawn_summary(
                    record.get("transport", "stdio"),
                    record.get("command") or "",
                    record.get("args") or "",
                    record.get("url") or "",
                ),
            )
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

    return f"Unknown action '{action}'. Use list, add, edit, remove, connect or disconnect."


def _server_list() -> str:
    from helpers.memory_db import all_mcp_servers

    records = all_mcp_servers()
    if not records:
        return "No MCP servers configured. Add one with action 'add'."

    connected = set(_client().all_connected())
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
