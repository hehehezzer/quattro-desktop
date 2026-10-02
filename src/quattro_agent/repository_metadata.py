"""Native host metadata queries never execute repository-configured helpers."""
from contextvars import ContextVar
from functools import wraps

_IDENTITY_ONLY = ContextVar("repository_identity_only", default=False)
_IDENTITY_COMMANDS = frozenset({"rev-parse", "branch", "symbolic-ref", "rev-list"})


def repository_status_allowed():
    return not _IDENTITY_ONLY.get()


def repository_command_allowed(arguments):
    return repository_status_allowed() or bool(arguments and (arguments[0] in _IDENTITY_COMMANDS
        or tuple(arguments) == ("worktree", "list", "--porcelain")))


def native_repository_metadata(function):
    """Scope native lifecycle metadata without changing concurrent ordinary tasks."""
    @wraps(function)
    def scoped(*args, **kwargs):
        token = _IDENTITY_ONLY.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _IDENTITY_ONLY.reset(token)
    return scoped


def native_task_metadata(function):
    """Apply identity-only metadata only when this call carries a native grant."""
    guarded = native_repository_metadata(function)
    @wraps(function)
    def scoped(*args, **kwargs):
        native = kwargs.get("native_grant") is not None
        if not native and function.__name__ in {"run_task", "validate_task"}:
            task_id = kwargs.get("task_id") or (args[1] if len(args) > 1 else None)
            if task_id is not None:
                task = args[0].store.get_task(task_id, include_private=True)
                native = task["private_payload"].get("nativeGrant") is not None
        return guarded(*args, **kwargs) if native else function(*args, **kwargs)
    return scoped
