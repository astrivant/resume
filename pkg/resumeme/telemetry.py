"""
Bridge application logging to OpenTelemetry JSON on stdout without exporting credentials.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import traceback
from contextlib import contextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from resumeme.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

__all__ = ["LOG_LEVELS", "logging_context", "safe_log_url", "set_log_level"]

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_URL = re.compile(r"https?://[^\s<>\"']+")
_SENSITIVE = re.compile(r"password|secret|token|authorization|cookie|private.?key|api.?key", re.IGNORECASE)


def safe_log_url(value: str) -> str:
    """
    Retain request destinations while removing credentials and opaque URL parameters.

    Args:
        value (str): Request URL, potentially containing a signed query or user information.

    Returns:
        str: Scheme, host, port, and path with redacted query and fragment markers.
    """
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""

        if ":" in host:
            host = f"[{host}]"

        if parsed.port is not None:
            host += f":{parsed.port}"

        return urlunsplit((parsed.scheme, host, parsed.path, "[REDACTED]" if parsed.query else "", "[REDACTED]" if parsed.fragment else ""))
    except ValueError:
        return "[invalid URL]"


def _redact(value: str) -> str:
    """
    Remove configured secrets and URL credentials from diagnostic strings.

    Args:
        value (str): Formatted message or string attribute before export.

    Returns:
        str: Diagnostic text with credential values and URL parameters replaced.
    """

    # Longer values go first so a shorter token cannot leave part of another credential visible.
    secrets = sorted(
        {
            secret
            for name, secret in os.environ.items()
            if secret and (_SENSITIVE.search(name) or name in {"LINKEDIN_USERNAME", "LINKEDIN_LOGIN"})
        },
        key=len,
        reverse=True,
    )

    for secret in secrets:
        value = value.replace(secret, "[REDACTED]")

    return _URL.sub(lambda match: safe_log_url(match.group()), value)


def _redact_value(value: object) -> object:
    """
    Apply the same redaction to nested structured attributes.

    Args:
        value (object): Log attribute supplied by application code.

    Returns:
        object: Sanitized scalar or collection with sensitive mapping entries removed.
    """
    if isinstance(value, str):
        return _redact(value)

    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SENSITIVE.search(str(key)) else _redact_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]

    return value


class _RedactCredentials(logging.Filter):
    """
    Sanitize messages and exception details before the OpenTelemetry bridge sees them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Replace sensitive values without discarding the event or its severity.

        Args:
            record (logging.LogRecord): Application record owned by this handler's logging context.

        Returns:
            bool: True after in-place sanitation.
        """
        record.msg = _redact(record.getMessage())
        record.args = ()

        # The upstream bridge derives exception attributes itself; clear the original exception after creating sanitized equivalents.
        if record.exc_info:
            error_type, error, _ = record.exc_info
            record.__dict__["exception.type"] = error_type.__name__ if error_type else "Exception"
            record.__dict__["exception.message"] = _redact(str(error))
            record.__dict__["exception.stacktrace"] = _redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
            record.exc_text = None

        for name, value in vars(record).copy().items():
            record.__dict__[name] = "[REDACTED]" if _SENSITIVE.search(name) else _redact_value(value)

        record.__dict__["logger.name"] = record.name
        return True


def set_log_level(level: str) -> None:
    """
    Set application verbosity without enabling raw third-party HTTP or browser logs.

    Args:
        level (str): Standard severity name, case-insensitive.

    Returns:
        None: Application logger threshold is updated.

    Raises:
        ConfigurationError: The level is not a supported named severity.
    """
    normalized = level.upper()

    if normalized not in LOG_LEVELS:
        raise ConfigurationError("Logging level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")

    logging.getLogger("resumeme").setLevel(normalized)


@contextmanager
def logging_context(level: str = "ERROR", *, stream: TextIO | None = None) -> Iterator[None]:
    """
    Export application records synchronously using the OpenTelemetry console JSON representation.

    Args:
        level (str): Initial application threshold; ERROR also covers configuration-loading failures.
        stream (TextIO | None): Caller-owned output stream; None selects stdout at invocation time.

    Yields:
        None: The application's logging namespace emits one JSON record per line until context exit.

    Raises:
        ConfigurationError: The initial level is invalid.
    """
    logger = logging.getLogger("resumeme")
    previous_level, previous_handlers, previous_propagate = logger.level, logger.handlers[:], logger.propagate
    set_log_level(level)
    provider = LoggerProvider(
        resource=Resource.create({"service.name": "resumeme", "service.version": version("resumeme")}), shutdown_on_exit=False
    )
    exporter = ConsoleLogRecordExporter(
        out=stream if stream is not None else sys.stdout, formatter=lambda record: record.to_json(indent=None) + "\n"
    )
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = LoggingHandler(logger_provider=provider)
    handler.addFilter(_RedactCredentials())

    # Own only this package's handlers. Raw Selenium logs can contain passwords, and enabling the root logger would export them.
    logger.handlers = [handler]
    logger.propagate = False

    try:
        yield
    finally:
        # Synchronous export prevents lost final errors; restoring state keeps repeated CLI calls and library hosts independent.
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
        provider.shutdown()
