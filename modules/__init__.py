import importlib
import os
from pathlib import Path


def discover_services():
    """Automatically import all service modules in this package."""
    current_dir = Path(__file__).parent

    for filename in sorted(os.listdir(current_dir)):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue

        module_name = filename[:-3]
        full_module_name = f"{__name__}.{module_name}"

        try:
            importlib.import_module(full_module_name)
        except Exception as e:
            from helpers.registry import ModuleStatus, ServiceRegistry

            if module_name not in ServiceRegistry._module_status:
                ServiceRegistry._module_status[module_name] = (
                    ModuleStatus.ERROR,
                    str(e),
                )
            print(f"Warning: could not load module '{module_name}': {e}")


discover_services()
