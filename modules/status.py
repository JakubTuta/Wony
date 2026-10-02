from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, register_job


@register_job(module_name="status", summary="What Wony can do, and what is broken")
@capture_response
def system_status(scope: str = "modules") -> str:
    """
    [SYSTEM INFORMATION JOB] Reports what Wony can do and what is wrong with it: which
    modules are working, what a broken one needs installing or configuring, the full
    list of available commands, or a retry of whatever failed to start.

    Args:
        scope (str): "modules" (the default) for each module's state and how to fix it,
            "setup" for a full checklist of .env, config and every integration,
            "commands" for everything Wony can be asked to do, or
            "retry" to try starting the broken modules again.

    Returns:
        str: The requested report.
    """
    wanted = (scope or "modules").strip().lower()

    if wanted in ("modules", "module", "status"):
        return _module_status()
    if wanted in ("setup", "doctor", "diagnostics", "check"):
        from modules.doctor import run_doctor

        return run_doctor()
    if wanted in ("commands", "help", "jobs"):
        return _commands()
    if wanted == "retry":
        return _retry_broken()

    return f"Unknown scope '{scope}'. Use modules, setup, commands or retry."


@register_job(module_name="status", summary="What Wony watches on its own")
@capture_response
def manage_triggers(action: str = "list", name: str = "") -> str:
    """
    [SYSTEM INFORMATION JOB] Lists the things Wony watches for on its own — the device
    running hot, a full disk, a meeting about to start, important mail, new mail, new
    calendar events — and turns one on or off. "Watch my inbox" is turning on
    new_email; "watch my calendar" is new_event. The choice is remembered.

    Args:
        action (str): "list" (the default), "off" or "on".
        name (str): Which one, e.g. "new_email". (required for off and on)

    Returns:
        str: What is being watched, or confirmation of the change.
    """
    from helpers import triggers

    wanted = (action or "list").strip().lower()

    if wanted in ("list", "show", "status"):
        return _trigger_list()

    if wanted not in ("off", "on", "disable", "enable", "stop", "start"):
        return f"Unknown action '{action}'. Use list, off or on."
    if not name:
        return "Error: which one? Ask for the list to see the names."

    known = {trigger.name for trigger in triggers.all_triggers()}
    if name not in known:
        return f"There is no '{name}'. Known: {', '.join(sorted(known))}."

    turning_on = wanted in ("on", "enable", "start")
    triggers.set_enabled(name, turning_on)
    state = "watching for" if turning_on else "no longer watching for"
    return f"I'm {state} {name.replace('_', ' ')}."


def _trigger_list() -> str:
    from helpers import triggers

    lines = ["Things I can watch for on my own:"]
    for trigger in triggers.all_triggers():
        state = "on" if triggers.is_on(trigger.name) else "off"
        lines.append(f"  - {trigger.name} ({state}): {trigger.watches}")
    if not triggers.enabled():
        lines.append(
            "'Speak up on its own' is off in Settings, so only the ones you "
            "turned on yourself are watched."
        )
    return "\n".join(lines)


def _module_status() -> str:
    statuses = ServiceRegistry.get_module_status()
    hints = ServiceRegistry.get_module_hints()

    if not statuses:
        return "No module status information available."

    col_name = max(len(name) for name in statuses) + 2
    col_state = 16

    lines = ["Module status:"]
    lines.append(f"  {'Module':<{col_name}} {'State':<{col_state}} Reason")
    lines.append("  " + "-" * (col_name + col_state + 30))

    state_order = {"enabled": 0, "disabled": 1, "misconfigured": 2, "unavailable": 3, "error": 4}
    sorted_items = sorted(statuses.items(), key=lambda x: (state_order.get(x[1][0], 5), x[0]))

    for name, (state, reason) in sorted_items:
        reason_str = f"  {reason}" if reason else ""
        lines.append(f"  {name:<{col_name}} {state:<{col_state}}{reason_str}")
        hint = hints.get(name, "")
        if hint and state != "enabled":
            lines.append(f"  {'':>{col_name}}   Fix: {hint}")

    return "\n".join(lines)


def _commands() -> str:
    job_modules = ServiceRegistry.get_job_modules()
    job_summaries = ServiceRegistry.get_job_summaries()

    grouped: dict = {}
    for job_name in ServiceRegistry.get_all_jobs():
        module = job_modules.get(job_name, "general")
        grouped.setdefault(module, []).append((job_name, job_summaries.get(job_name, "")))

    lines = ["Available commands:"]
    for module in sorted(grouped):
        lines.append(f"\n  [{module or 'general'}]")
        for name, summary in sorted(grouped[module]):
            display = name.replace("_", " ")
            lines.append(f"    {display} — {summary}" if summary else f"    {display}")

    return "\n".join(lines)


def _retry_broken() -> str:
    """Re-run initialization for everything that failed to start.

    Same path the background health watcher uses, exposed so a user who has just
    installed a missing package does not have to restart the app or wait for the
    next sweep.
    """
    retryable = ServiceRegistry.get_retryable_modules()
    if not retryable:
        return "Nothing is waiting to be retried."

    recovered, still_broken = [], []
    for module_name in retryable:
        try:
            if ServiceRegistry.reinitialize_module(module_name):
                recovered.append(module_name)
            else:
                still_broken.append(module_name)
        except Exception as e:
            still_broken.append(f"{module_name} ({e})")

    parts = []
    if recovered:
        parts.append(f"Now working: {', '.join(recovered)}.")
    if still_broken:
        parts.append(f"Still not working: {', '.join(still_broken)}.")
    return " ".join(parts)
