"""Public error types for the evals module.

Kept in a tiny module of their own so the user can `except` them without
importing anything heavy. The module imports nothing beyond the stdlib.
"""


class EvalError(Exception):
    """Base class — catch this to handle any vigilai.evals failure."""


class EvalDependenciesNotInstalled(EvalError):
    """Raised when an evaluator needs the optional `vigilai[evals]` extras
    and they are not installed in the running environment."""


class RubricError(EvalError, ValueError):
    """Raised when a YAML rubric is malformed or fails structural validation."""


class NoLLMConfigured(EvalError):
    """Raised when no LLM provider key is available (judge needs one)."""


class DashboardError(EvalError):
    """Raised when a dashboard-backed eval call fails (HTTP error, bad
    response shape, etc.). Unlike `AIGovLogger.call`, dashboard eval calls
    are user-driven and we DO raise — silent failure would hide real bugs."""
