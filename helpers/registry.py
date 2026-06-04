import os
import typing

import dotenv

dotenv.load_dotenv()
T = typing.TypeVar("T")


class ModuleStatus:
    ENABLED = "enabled"
    DISABLED = "disabled"
    MISCONFIGURED = "misconfigured"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ServiceRegistry:
    """Registry for managing jobs and services with module-level gating."""

    _jobs: typing.Dict[str, typing.Callable] = {}
    _services: typing.Dict[str, typing.Any] = {}
    _service_instances: typing.Dict[str, typing.Any] = {}
    _module_status: typing.Dict[str, typing.Tuple[str, str]] = {}
    _module_hints: typing.Dict[str, str] = {}
    _job_modules: typing.Dict[str, str] = {}
    _job_summaries: typing.Dict[str, str] = {}

    @classmethod
    def get_all_jobs(cls) -> typing.Dict[str, typing.Callable]:
        return cls._jobs.copy()

    @classmethod
    def get_service_instance(cls, service_name: str) -> typing.Any:
        return cls._service_instances.get(service_name)

    @classmethod
    def get_module_status(cls) -> typing.Dict[str, typing.Tuple[str, str]]:
        return cls._module_status.copy()

    @classmethod
    def get_module_hints(cls) -> typing.Dict[str, str]:
        return cls._module_hints.copy()

    @classmethod
    def get_job_modules(cls) -> typing.Dict[str, str]:
        return cls._job_modules.copy()

    @classmethod
    def get_job_summaries(cls) -> typing.Dict[str, str]:
        return cls._job_summaries.copy()

    @classmethod
    def _check_module_enabled(
        cls, module_name: typing.Optional[str]
    ) -> typing.Tuple[bool, str]:
        if module_name is None:
            return True, ""
        try:
            from helpers.config import Config

            if not Config.is_module_enabled(module_name):
                return False, "not in enabled_modules"
        except Exception:
            pass
        return True, ""

    @classmethod
    def _check_requirements(cls, requires: typing.Any) -> typing.Tuple[bool, str]:
        if requires is None:
            return True, ""
        try:
            from helpers.requirements import evaluate

            return evaluate(requires)
        except Exception as e:
            return False, str(e)

    @classmethod
    def _status_for_reason(cls, reason: str) -> str:
        if "pip module" in reason:
            return ModuleStatus.UNAVAILABLE
        return ModuleStatus.MISCONFIGURED

    @classmethod
    def _extract_summary(cls, func: typing.Callable) -> str:
        """Extract first meaningful line from a docstring, stripping [... JOB] tags."""
        doc = func.__doc__ or ""
        for line in doc.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip [... JOB] / [... METHOD] style tags
            if line.startswith("[") and "]" in line:
                line = line[line.index("]") + 1:].strip()
            if line:
                return line[:80]
        return ""

    @classmethod
    def register_job(
        cls,
        name_or_func: typing.Union[str, typing.Callable, None] = None,
        *,
        module_name: typing.Optional[str] = None,
        requires: typing.Any = None,
        summary: str = "",
    ):
        """
        Decorator to register a standalone job function.

        Usage:
            @register_job
            def my_job(): ...

            @register_job(module_name="weather", requires=Requirement(...))
            def weather(city): ...
        """

        def decorator(func):
            job_name = name_or_func if isinstance(name_or_func, str) else func.__name__

            if not func.__doc__:
                raise ValueError(f"Job '{job_name}' must have documentation")

            enabled, reason = cls._check_module_enabled(module_name)
            if not enabled:
                if module_name:
                    cls._module_status[module_name] = (ModuleStatus.DISABLED, reason)
                return func

            ready, reason = cls._check_requirements(requires)
            if not ready:
                if module_name:
                    cls._module_status[module_name] = (
                        cls._status_for_reason(reason),
                        reason,
                    )
                    if requires and getattr(requires, "setup_hint", ""):
                        cls._module_hints[module_name] = requires.setup_hint
                return func

            cls._jobs[job_name] = func
            cls._job_modules[job_name] = module_name or ""
            cls._job_summaries[job_name] = summary or cls._extract_summary(func)
            if module_name and module_name not in cls._module_status:
                cls._module_status[module_name] = (ModuleStatus.ENABLED, "")
            return func

        if callable(name_or_func):
            return decorator(name_or_func)

        return decorator

    @classmethod
    def register_service(
        cls,
        service_class: typing.Optional[type] = None,
        *,
        module_name: typing.Optional[str] = None,
        requires: typing.Any = None,
    ):
        """
        Register a service class with optional module gating and requirement checks.

        Usage:
            @register_service
            class MyService: ...

            @register_service(module_name="spotify", requires=Requirement(...))
            class Spotify: ...
        """

        def do_register(svc_class: type) -> type:
            svc_module_name = module_name or svc_class.__name__.lower()

            enabled, reason = cls._check_module_enabled(svc_module_name)
            if not enabled:
                cls._module_status[svc_module_name] = (ModuleStatus.DISABLED, reason)
                return svc_class

            ready, reason = cls._check_requirements(requires)
            if not ready:
                cls._module_status[svc_module_name] = (
                    cls._status_for_reason(reason),
                    reason,
                )
                if requires and getattr(requires, "setup_hint", ""):
                    cls._module_hints[svc_module_name] = requires.setup_hint
                return svc_class

            cls._services[svc_module_name] = svc_class

            try:
                instance = svc_class()
                cls._service_instances[svc_module_name] = instance

                for attr_name in dir(instance):
                    attr = getattr(instance, attr_name)
                    if hasattr(attr, "_is_job_method"):
                        job_name = getattr(attr, "_job_name", attr_name)
                        cls._jobs[job_name] = attr
                        cls._job_modules[job_name] = svc_module_name
                        explicit_summary = getattr(attr, "_job_summary", "")
                        cls._job_summaries[job_name] = (
                            explicit_summary or cls._extract_summary(attr)
                        )

                cls._module_status[svc_module_name] = (ModuleStatus.ENABLED, "")

            except Exception as e:
                print(f"Failed to initialize {svc_class.__name__}: {e}")
                cls._services.pop(svc_module_name, None)
                cls._service_instances.pop(svc_module_name, None)
                cls._module_status[svc_module_name] = (ModuleStatus.ERROR, str(e))

            return svc_class

        if service_class is not None:
            return do_register(service_class)
        return do_register

    @classmethod
    def method_job(
        cls, name_or_method: typing.Union[str, typing.Callable, None] = None, *, summary: str = ""
    ):
        """
        Decorator to mark service methods as jobs.

        Usage:
            class MyService:
                @method_job
                def my_method(self): ...
        """

        def decorator(method):
            method_name = (
                name_or_method if isinstance(name_or_method, str) else method.__name__
            )

            if not method.__doc__:
                raise ValueError(f"Method '{method_name}' must have documentation")

            method._is_job_method = True
            method._job_name = method_name
            method._job_summary = summary
            return method

        if callable(name_or_method):
            return decorator(name_or_method)

        return decorator


def service_with_env_check(*env_vars: str):
    """
    Backward-compat shim. Registers a service with env var requirement checks.
    Module name is derived from the class name.
    """
    from helpers.requirements import Requirement

    def decorator(service_class):
        req = Requirement(env_vars=list(env_vars)) if env_vars else None
        return ServiceRegistry.register_service(
            service_class,
            module_name=service_class.__name__.lower(),
            requires=req,
        )

    return decorator


def simple_service(service_class):
    """Register a service class without requirement checks (always-on)."""
    return ServiceRegistry.register_service(service_class)


register_job = ServiceRegistry.register_job
method_job = ServiceRegistry.method_job
register_service = ServiceRegistry.register_service
