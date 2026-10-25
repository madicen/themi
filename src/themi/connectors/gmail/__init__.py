"""Gmail: the REST client, message parsing, polling and the email executors."""

from themi.connectors.gmail.client import (
    GmailAuthError,
    GmailClient,
    GmailError,
    HistoryExpired,
    RateLimited,
)
from themi.connectors.gmail.executors import install_executors
from themi.connectors.gmail.parse import Attachment, GmailMessage, parse_message
from themi.connectors.gmail.sync import EmailReceived, GmailSync

__all__ = [
    "Attachment",
    "EmailReceived",
    "GmailAuthError",
    "GmailClient",
    "GmailError",
    "GmailMessage",
    "GmailSync",
    "HistoryExpired",
    "RateLimited",
    "install_executors",
    "parse_message",
]
