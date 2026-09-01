"""Typed failures raised by the durable harness core."""


class HarnessError(RuntimeError):
    """Base class for harness failures that callers may present safely."""


class ConfigError(HarnessError):
    """Configuration is malformed, unsupported, or unsafe."""


class PrivacyError(HarnessError):
    """Private or unbounded data was offered to a display-safe surface."""


class StateTransitionError(HarnessError):
    """A requested lifecycle transition is not allowed."""


class PolicyEscalationError(HarnessError):
    """A child policy exceeds the authority granted to its parent."""


class LeaseConflict(HarnessError):
    """One or more requested scheduler resources are unavailable."""


class WorkflowError(HarnessError):
    """A workflow graph or join operation is invalid."""


class SupervisorError(HarnessError):
    """A child process could not be safely launched or supervised."""


class ProcessIdentityError(SupervisorError):
    """A persisted PID no longer identifies the expected process."""
