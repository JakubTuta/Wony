from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, register_job


@register_job
@capture_response
def module_status() -> str:
    """
    [SYSTEM INFORMATION JOB] Shows the status of all available modules, including fix hints.
    Displays whether each module is enabled, disabled, misconfigured, or unavailable,
    and tells you exactly what to do to fix each issue.

    Use this job when the user wants to:
    - See which modules are active
    - Diagnose why a module is not working
    - Check what integrations are configured
    - Get fix instructions for broken modules

    Keywords: module status, status, modules, what modules, which modules, available modules,
             check modules, module health, enabled modules, module list, what's working

    Args:
        None

    Returns:
        str: Formatted table of module names, states, reasons, and fix hints.
    """
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
