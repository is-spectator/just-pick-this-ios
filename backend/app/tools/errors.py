from __future__ import annotations


class ToolError(Exception):
    code = "tool_error"


class ToolValidationError(ToolError):
    code = "tool_validation_error"


class ToolNotFoundError(ToolError):
    code = "tool_not_found"


class ToolConflictError(ToolError):
    code = "tool_conflict"


class ToolForbiddenError(ToolError):
    code = "tool_forbidden"
