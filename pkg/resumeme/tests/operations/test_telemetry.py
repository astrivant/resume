"""
Verify OpenTelemetry console records, verbosity, request diagnostics, and credential redaction.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO, StringIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import requests
from jsonschema import ValidationError
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from resumeme.cli import main
from resumeme.compiler.asts.profile import Profile, save_profile
from resumeme.config import Config, LinkedIn, load_config
from resumeme.linkedin.media import fetch_public
from resumeme.telemetry import logging_context

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


def test_default_error_logs_use_otel_json_and_stdout(capsys: CaptureFixture[str]) -> None:
    """
    Export errors synchronously while suppressing less severe events by default.

    Args:
        capsys (CaptureFixture[str]): Captures the actual stdout and stderr destinations.

    Returns:
        None: One OpenTelemetry ERROR record appears on stdout with timestamps and service identity.
    """
    with logging_context():
        logger = logging.getLogger("resumeme.test")
        logger.debug("Hidden debug")
        logger.info("Hidden info")
        logger.warning("Hidden warning")
        logger.error("Observed failure")

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    record = json.loads(captured.out)
    assert record["body"] == "Observed failure"
    assert record["severity_number"] == 17
    assert record["severity_text"] == "ERROR"
    assert record["timestamp"].endswith("Z")
    assert record["observed_timestamp"].endswith("Z")
    assert record["resource"]["attributes"]["service.name"] == "resumeme"
    assert record["attributes"]["logger.name"] == "resumeme.test"


@pytest.mark.parametrize(
    "level,numbers", [("DEBUG", [5, 9, 13, 17, 21]), ("INFO", [9, 13, 17, 21]), ("WARNING", [13, 17, 21]), ("CRITICAL", [21])]
)
def test_level_threshold_and_trace_context(level: str, numbers: list[int]) -> None:
    """
    Preserve standard severity mappings and any existing OpenTelemetry trace context.

    Args:
        level (str): Configured minimum severity.
        numbers (list[int]): Expected OpenTelemetry severities after filtering.

    Returns:
        None: Log records inherit trace identifiers and include only enabled severities.
    """
    output = StringIO()
    span = NonRecordingSpan(SpanContext(trace_id=123, span_id=456, is_remote=False, trace_flags=TraceFlags(1)))

    with logging_context(level, stream=output), use_span(span):
        for severity in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
            logging.getLogger("resumeme.test").log(severity, "Event")

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["severity_number"] for record in records] == numbers
    assert all(record["trace_id"] == f"0x{123:032x}" and record["span_id"] == f"0x{456:016x}" for record in records)


def test_logging_context_restores_handlers_without_duplicates() -> None:
    """
    Keep embedded library hosts and repeat CLI invocations independent.

    Returns:
        None: Existing logger state is restored and repeated setup emits each event once.
    """
    logger = logging.getLogger("resumeme")
    before = logger.level, logger.handlers[:], logger.propagate
    output = StringIO()

    for _ in range(2):
        with logging_context(stream=output):
            logger.error("Once")

    assert (logger.level, logger.handlers, logger.propagate) == before
    assert len(output.getvalue().splitlines()) == 2
    assert not output.closed


def test_secrets_are_redacted_from_messages_attributes_and_exceptions(monkeypatch: MonkeyPatch) -> None:
    """
    Redact credentials before the SDK serializes log bodies and structured details.

    Args:
        monkeypatch (MonkeyPatch): Supplies synthetic secret values unavailable to the exporter.

    Returns:
        None: Neither secrets, URL credentials, query values, nor nested sensitive fields appear in JSON output.
    """
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-api-key")
    monkeypatch.setenv("LINKEDIN_USERNAME", "login@example.org")
    output = StringIO()

    with logging_context("DEBUG", stream=output):
        try:
            raise ValueError("synthetic-password at https://user:credential@example.org/path?token=hidden-query#hidden-fragment")
        except ValueError:
            logging.getLogger("resumeme.test").exception(
                "Failed for %s with %s",
                "login@example.org",
                "synthetic-api-key",
                extra={
                    "headers": {"Authorization": "private-header", "Cookie": "private-cookie"},
                    "details": ["synthetic-password"],
                },
            )

    text = output.getvalue()

    for secret in (
        "synthetic-password",
        "synthetic-api-key",
        "login@example.org",
        "credential",
        "hidden-query",
        "hidden-fragment",
        "private-header",
        "private-cookie",
    ):
        assert secret not in text

    record = json.loads(text)
    assert record["attributes"]["exception.type"] == "ValueError"
    assert "https://example.org/path?[REDACTED]#[REDACTED]" in record["attributes"]["exception.message"]
    assert "[REDACTED]" in record["body"]


def test_debug_http_logs_capture_requests_redirects_and_sizes(monkeypatch: MonkeyPatch) -> None:
    """
    Observe HTTP metadata without enabling urllib3 or Selenium payload logging.

    Args:
        monkeypatch (MonkeyPatch): Replaces network validation and timing with deterministic values.

    Returns:
        None: Both redirect hops log status and duration, downloads log size, and bodies and headers remain private.
    """
    monkeypatch.setattr("resumeme.linkedin.media._validate_remote", lambda url: None)
    monkeypatch.setattr("resumeme.linkedin.media.monotonic", MagicMock(side_effect=[1.0, 1.25, 2.0, 2.25, 2.5]))
    redirect, response = requests.Response(), requests.Response()
    redirect.status_code = 302
    redirect.headers["Location"] = "https://example.org/final?signed=private-query"
    redirect.raw = BytesIO()
    response.status_code = 200
    response.raw = BytesIO(b"private-response-body")
    response.headers["Set-Cookie"] = "private-cookie"
    session = MagicMock(spec=requests.Session)
    session.cookies = MagicMock()
    session.get.side_effect = [redirect, response]
    output = StringIO()
    root_level = logging.getLogger().level

    with logging_context("DEBUG", stream=output):
        body, destination = fetch_public(session, "https://example.org/start?token=private-query", 30)

    assert body == b"private-response-body"
    assert destination == "https://example.org/final?signed=private-query"
    assert logging.getLogger().level == root_level
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    statuses = [record["attributes"]["http.response.status_code"] for record in records if record["body"] == "HTTP response received"]
    assert statuses == [302, 200]
    assert records[-1]["attributes"]["http.response.body.size"] == len(body)
    assert records[-1]["attributes"]["request.duration_seconds"] == 0.5
    assert all(record["severity_text"] == "DEBUG" for record in records)

    for private in ("private-query", "private-cookie", "private-response-body"):
        assert private not in output.getvalue()


@pytest.mark.parametrize(
    "configured,environment,argument,expected",
    [
        ("ERROR", None, None, []),
        ("INFO", None, None, ["INFO"]),
        ("ERROR", "info", None, ["INFO"]),
        ("DEBUG", "ERROR", None, []),
        ("ERROR", "ERROR", "debug", ["INFO", "DEBUG"]),
    ],
)
def test_cli_log_level_precedence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    configured: str,
    environment: str | None,
    argument: str | None,
    expected: list[str],
) -> None:
    """
    Resolve CLI, environment, and YAML levels while retaining normal command results.

    Args:
        tmp_path (Path): Temporary config and minimal accepted profile.
        monkeypatch (MonkeyPatch): Isolates the environment override.
        capsys (CaptureFixture[str]): Captures structured logs and the validation result.
        configured (str): YAML severity.
        environment (str | None): Optional environment override.
        argument (str | None): Optional command-line override.
        expected (list[str]): Severities emitted by the command's start and configuration events.

    Returns:
        None: The highest-precedence setting wins and stdout retains the validation result.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\nlogging: {{level: {configured}}}\n")
    save_profile(Profile("example", "Example"), tmp_path / "data/profile.json")
    monkeypatch.delenv("RESUMEME_LOG_LEVEL", raising=False)

    if environment is not None:
        monkeypatch.setenv("RESUMEME_LOG_LEVEL", environment)

    arguments = ["--config", str(path), *(["--log-level", argument] if argument else []), "validate"]
    assert main(arguments) == 0
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines() if line.startswith("{")]
    assert [record["severity_text"] for record in records] == expected
    assert "Valid profile: Example" in captured.out
    assert captured.err == ""


def test_bad_configuration_reports_an_otel_error_before_loading(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """
    Keep logging available when configuration cannot be opened.

    Args:
        tmp_path (Path): Directory containing no config.
        capsys (CaptureFixture[str]): Captures the bootstrap error record.
        monkeypatch (MonkeyPatch): Removes any inherited verbosity override.

    Returns:
        None: The command returns two and emits its actionable error as JSON on stdout.
    """
    monkeypatch.delenv("RESUMEME_LOG_LEVEL", raising=False)
    assert main(["--config", str(tmp_path / "missing.yaml"), "validate"]) == 2
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert record["severity_number"] == 17
    assert record["attributes"]["error.type"] == "FileNotFoundError"
    assert captured.err == ""


@pytest.mark.parametrize("setting", ["{level: TRACE}", "{level: false}", "{level: null}", "{level: ERROR, typo: true}"])
def test_logging_schema_rejects_invalid_settings(tmp_path: Path, setting: str) -> None:
    """
    Validate logging settings before executing commands or fetching remote resources.

    Args:
        tmp_path (Path): Temporary configuration root.
        setting (str): Invalid logging mapping.

    Returns:
        None: Unknown levels, types, and fields fail schema validation; omitted settings default to ERROR.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\nlogging: {setting}\n")

    with pytest.raises(ValidationError):
        load_config(path)

    assert Config(LinkedIn("example")).logging.level == "ERROR"
