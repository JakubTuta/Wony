import re
import threading
import typing

import dotenv

dotenv.load_dotenv()
T = typing.TypeVar("T")

_interactive_local = threading.local()


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
    # Jobs that change something the user cares about. Declared at the job, not
    # in a hand-kept list of bare strings somewhere else that nothing validates.
    # Deliberately absent from the tool schema: it would cost tokens on every
    # request and models are unreliable at self-restraint. It is read on the
    # execution side instead — see helpers/confirm.py and helpers/web_app.py.
    # True for every call, or a collection of `action` argument values that
    # need confirming — a merged job whose default action only reads must not
    # make the user confirm a question.
    _job_confirms: typing.Dict[str, typing.Any] = {}
    # Declared requirement per module, recorded whatever the outcome — this is
    # what `doctor` reports against, so it must not be a second hand-kept list.
    _module_requirements: typing.Dict[str, typing.Any] = {}
    # Stores enough info to retry failed modules at runtime.
    # service: {"kind": "service", "cls": type, "requires": Requirement|None}
    # jobs:    {"kind": "jobs", "items": [(job_name, func, requires, summary, confirms), ...]}
    _reinit_pending: typing.Dict[str, typing.Dict] = {}

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
    def get_job_confirms(cls) -> typing.Dict[str, typing.Any]:
        return cls._job_confirms.copy()

    @classmethod
    def job_confirms(cls, job_name: str) -> bool:
        return bool(cls._job_confirms.get(job_name))

    @classmethod
    def get_module_requirements(cls) -> typing.Dict[str, typing.Any]:
        return cls._module_requirements.copy()

    @classmethod
    def declare_requirement(cls, module_name: typing.Optional[str], requires: typing.Any) -> None:
        """Record a module's declared requirement. Called at decoration time,
        before any gating, so a disabled or broken module is still reportable."""
        if module_name and requires is not None:
            cls._module_requirements.setdefault(module_name, requires)

    @classmethod
    def get_retryable_modules(cls) -> typing.List[str]:
        """Modules that failed init and have enough info for a retry attempt."""
        retryable = []
        for name in cls._reinit_pending:
            status, _ = cls._module_status.get(name, (None, ""))
            # UNAVAILABLE belongs here too: "pip install -r requirements/web.txt"
            # is the single most common fix, and leaving it out meant the module
            # stayed off until the whole app was restarted.
            if status in (
                ModuleStatus.ERROR,
                ModuleStatus.MISCONFIGURED,
                ModuleStatus.UNAVAILABLE,
            ):
                retryable.append(name)
        return retryable

    @classmethod
    def interactive_allowed(cls) -> bool:
        """True unless the current call stack is a non-interactive reinit
        (e.g. the health-watcher's automatic retry loop) — services that
        would otherwise pop up a browser/OAuth flow should raise instead."""
        return getattr(_interactive_local, "value", True)

    @classmethod
    def reinitialize_module(cls, module_name: str, interactive: bool = True) -> bool:
        """
        Attempt to re-initialize a previously failed module.
        Returns True if the module is now ENABLED.
        Safe to call from any thread; caller should handle exceptions.

        interactive: False for automatic/background retries (health watcher) —
        services that need user interaction (e.g. Spotify OAuth) should check
        interactive_allowed() and raise rather than popping up a browser.
        """
        prev_interactive = getattr(_interactive_local, "value", True)
        _interactive_local.value = interactive
        try:
            pending = cls._reinit_pending.get(module_name)
            if not pending:
                return False

            status, _ = cls._module_status.get(module_name, (None, ""))
            if status == ModuleStatus.DISABLED:
                return False

            kind = pending["kind"]

            if kind == "service":
                svc_class = pending["cls"]
                requires = pending["requires"]

                ready, reason = cls._check_requirements(requires)
                if not ready:
                    cls._module_status[module_name] = (cls._status_for_reason(reason), reason)
                    return False

                try:
                    instance = svc_class()
                    cls._service_instances[module_name] = instance
                    cls._services[module_name] = svc_class

                    for attr_name in dir(instance):
                        attr = getattr(instance, attr_name)
                        if hasattr(attr, "_is_job_method"):
                            job_name = getattr(attr, "_job_name", attr_name)
                            cls._jobs[job_name] = attr
                            cls._job_modules[job_name] = module_name
                            explicit_summary = getattr(attr, "_job_summary", "")
                            cls._job_summaries[job_name] = explicit_summary or cls._extract_summary(attr)
                            cls._job_confirms[job_name] = getattr(attr, "_job_confirms", False)

                    cls._module_status[module_name] = (ModuleStatus.ENABLED, "")
                    cls._reinit_pending.pop(module_name, None)
                    return True
                except Exception as e:
                    cls._module_status[module_name] = (ModuleStatus.ERROR, str(e))
                    return False

            if kind == "jobs":
                return cls._reinitialize_jobs_kind(module_name, pending)
            return False
        finally:
            _interactive_local.value = prev_interactive

    @classmethod
    def _reinitialize_jobs_kind(cls, module_name: str, pending: typing.Dict) -> bool:
        items = pending["items"]
        registered = []
        for job_name, func, requires, summary, confirms in items:
            ready, reason = cls._check_requirements(requires)
            if not ready:
                cls._module_status[module_name] = (cls._status_for_reason(reason), reason)
                return False
            registered.append((job_name, func, summary, confirms))

        for job_name, func, summary, confirms in registered:
            cls._jobs[job_name] = func
            cls._job_modules[job_name] = module_name
            cls._job_summaries[job_name] = summary or cls._extract_summary(func)
            cls._job_confirms[job_name] = confirms

        cls._module_status[module_name] = (ModuleStatus.ENABLED, "")
        cls._reinit_pending.pop(module_name, None)
        return True

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
        """First full sentence of a docstring's opening paragraph, for UI job lists.

        Docstrings are hand-wrapped across several source lines for
        readability — joining them before cutting is what keeps this from
        handing the UI a summary sliced off mid-sentence at whatever column
        the source happened to wrap.
        """
        doc = func.__doc__ or ""
        paragraph: typing.List[str] = []
        for line in doc.splitlines():
            line = line.strip()
            if not line:
                if paragraph:
                    break
                continue
            paragraph.append(line)
        text = " ".join(paragraph)
        # Strip [... JOB] / [... METHOD] style tags
        if text.startswith("[") and "]" in text:
            text = text[text.index("]") + 1:].strip()
        match = re.match(r".{1,240}?[.!?](?=\s|$)", text)
        return match.group(0) if match else text[:240]

    @classmethod
    def register_job(
        cls,
        name_or_func: typing.Union[str, typing.Callable, None] = None,
        *,
        module_name: typing.Optional[str] = None,
        requires: typing.Any = None,
        summary: str = "",
        confirms: typing.Any = False,
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

            cls.declare_requirement(module_name, requires)

            # On the function, not just in the registry: whether a job needs
            # confirming is a property of the job, and it has to be readable
            # even when the module it lives in is switched off — otherwise the
            # test that every destructive job declares a gate can only see the
            # modules the developer happens to have enabled. method_job stores
            # it the same way.
            func._job_confirms = confirms

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
                    # Store for later retry by health watcher
                    entry = cls._reinit_pending.setdefault(
                        module_name, {"kind": "jobs", "items": []}
                    )
                    entry["items"].append(
                        (job_name, func, requires,
                         summary or cls._extract_summary(func), confirms)
                    )
                return func

            cls._jobs[job_name] = func
            cls._job_modules[job_name] = module_name or ""
            cls._job_summaries[job_name] = summary or cls._extract_summary(func)
            cls._job_confirms[job_name] = confirms
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

            cls.declare_requirement(svc_module_name, requires)

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
                # Store for later retry by health watcher
                cls._reinit_pending[svc_module_name] = {
                    "kind": "service", "cls": svc_class, "requires": requires
                }
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
                        cls._job_confirms[job_name] = getattr(
                            attr, "_job_confirms", False
                        )

                cls._module_status[svc_module_name] = (ModuleStatus.ENABLED, "")

            except Exception as e:
                cls._services.pop(svc_module_name, None)
                cls._service_instances.pop(svc_module_name, None)
                cls._module_status[svc_module_name] = (ModuleStatus.ERROR, str(e))
                # Store for retry — requirements passed, init itself failed (e.g. no device)
                cls._reinit_pending[svc_module_name] = {
                    "kind": "service", "cls": svc_class, "requires": requires
                }

            return svc_class

        if service_class is not None:
            return do_register(service_class)
        return do_register

    @classmethod
    def method_job(
        cls,
        name_or_method: typing.Union[str, typing.Callable, None] = None,
        *,
        summary: str = "",
        confirms: typing.Any = False,
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
            method._job_confirms = confirms
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
