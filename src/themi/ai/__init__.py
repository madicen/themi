"""AI backends behind one interface, with one retry policy.

Code outside this package reaches a model only through the router (prompt 06).
"""

from themi.ai.errors import (
    AIError,
    CapabilityError,
    PermanentError,
    RefusalError,
    RetriesExhausted,
    RetryableError,
)
from themi.ai.provider import Capabilities, Provider
from themi.ai.retry import RetryPolicy, call_with_retry
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Message,
    StopReason,
    StructuredResponse,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    Transcription,
    Usage,
)

__all__ = [
    "AIError",
    "CallKind",
    "Capabilities",
    "CapabilityError",
    "ChatResponse",
    "Message",
    "PermanentError",
    "Provider",
    "RefusalError",
    "RetriesExhausted",
    "RetryPolicy",
    "RetryableError",
    "StopReason",
    "StructuredResponse",
    "TextBlock",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Transcription",
    "Usage",
    "call_with_retry",
]
