"""
Redact and summarize Trivy reports for CI artifacts and pull request comments.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TypeGuard

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]

SECRET_FIELDS = frozenset({"RuleID", "Category", "Severity", "Title", "StartLine", "EndLine", "Layer", "Match"})
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
COMMENT_MARKER = "<!-- resumeme-trivy-scan -->"


@dataclass(frozen=True)
class Finding:
    """
    Retain only safe fields needed for concise CI summaries.

    Attributes:
        kind (str): Trivy finding category.
        severity (str): Finding severity normalized to uppercase.
        target (str): Repository path or dependency target.
        title (str): Rule title or vulnerability identifier.
        line (str): Source line for a secret finding, when available.
        identifier (str): Secret rule or vulnerability identifier.
        package (str): Vulnerable package name, when available.
        installed (str): Installed package version, when available.
        fixed (str): Fixed package version, when available.
    """

    kind: str
    severity: str
    target: str
    title: str
    line: str
    identifier: str
    package: str
    installed: str
    fixed: str


def is_json_value(value: object) -> TypeGuard[JSONValue]:
    """
    Validate parsed JSON recursively before treating it as a report.

    Args:
        value (object): Value returned by the JSON decoder.

    Returns:
        TypeGuard[JSONValue]: Whether the value contains only JSON-compatible values.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return True

    if isinstance(value, list):
        return all(is_json_value(item) for item in value)

    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())

    return False


def load_report(path: Path) -> dict[str, JSONValue]:
    """
    Load a JSON object from a Trivy report path.

    Args:
        path (Path): Raw or sanitized Trivy JSON report.

    Returns:
        dict[str, JSONValue]: Parsed report object.

    Raises:
        OSError: The report cannot be read.
        ValueError: The report is invalid JSON or is not a JSON object.
    """
    parsed: object = json.loads(path.read_text(encoding="utf-8"))

    if not is_json_value(parsed) or not isinstance(parsed, dict):
        raise ValueError("Trivy report must contain a JSON object")

    return parsed


def sanitize_report(value: JSONValue) -> JSONValue:
    """
    Remove source snippets and redact matched text before report publication.

    Args:
        value (JSONValue): Parsed Trivy report.

    Returns:
        JSONValue: Report with secret code snippets removed and match fields redacted.
    """
    if isinstance(value, list):
        return [sanitize_report(item) for item in value]

    if not isinstance(value, dict):
        return value

    sanitized: dict[str, JSONValue] = {}

    # Trivy report fields can nest, so remove snippets and matched text wherever the schema places them.
    for key, item in value.items():
        if key.lower() == "code":
            continue

        if key.lower() == "match":
            sanitized[key] = "<redacted>"
            continue

        if key == "Secrets" and isinstance(item, list):
            sanitized[key] = [sanitize_secret(secret) for secret in item]
            continue

        sanitized[key] = sanitize_report(item)

    return sanitized


def sanitize_secret(value: JSONValue) -> JSONValue:
    """
    Keep a strict allowlist of non-content metadata for secret findings.

    Args:
        value (JSONValue): Secret finding from a Trivy report.

    Returns:
        JSONValue: Secret metadata without matched content or source snippets.
    """
    if not isinstance(value, dict):
        return {}

    secret: dict[str, JSONValue] = {}

    # Keep stable rule and location metadata while excluding any future fields by default.
    for key, item in value.items():
        if key not in SECRET_FIELDS:
            continue

        secret[key] = "<redacted>" if key == "Match" else item

    if "Match" not in secret:
        secret["Match"] = "<redacted>"

    return secret


def _mapping(value: JSONValue | None) -> dict[str, JSONValue]:
    """
    Return a mapping value or an empty mapping.

    Args:
        value (JSONValue | None): Value to inspect.

    Returns:
        dict[str, JSONValue]: Mapping or empty fallback.
    """
    return value if isinstance(value, dict) else {}


def _sequence(value: JSONValue | None) -> list[JSONValue]:
    """
    Return a sequence value or an empty sequence.

    Args:
        value (JSONValue | None): Value to inspect.

    Returns:
        list[JSONValue]: Sequence or empty fallback.
    """
    return value if isinstance(value, list) else []


def _text(value: JSONValue | None, default: str = "") -> str:
    """
    Return a bounded string representation for a JSON scalar.

    Args:
        value (JSONValue | None): Value to format.
        default (str): Fallback for objects and null values.

    Returns:
        str: Single-line, bounded string value.
    """
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ").strip()[:160]

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)

    return default


def collect_findings(report: dict[str, JSONValue]) -> list[Finding]:
    """
    Extract secret and vulnerability metadata without reading match contents.

    Args:
        report (dict[str, JSONValue]): Sanitized Trivy report.

    Returns:
        list[Finding]: Safe finding summaries used for check output and PR comments.
    """
    findings: list[Finding] = []

    for result_value in _sequence(report.get("Results")):
        result = _mapping(result_value)
        target = _text(result.get("Target"), "unknown target")

        # Read only the secret and vulnerability fields needed for summaries; never include a match value.
        for kind, key in (("secret", "Secrets"), ("vulnerability", "Vulnerabilities")):
            for finding_value in _sequence(result.get(key)):
                finding = _mapping(finding_value)
                identifier_key = "RuleID" if kind == "secret" else "VulnerabilityID"
                identifier = _text(finding.get(identifier_key), "unknown rule")
                line_number = _text(finding.get("StartLine")) if kind == "secret" else ""
                findings.append(
                    Finding(
                        kind=kind,
                        severity=_text(finding.get("Severity"), "UNKNOWN").upper(),
                        target=target,
                        title=_text(finding.get("Title"), identifier),
                        line=line_number,
                        identifier=identifier,
                        package=_text(finding.get("PkgName")),
                        installed=_text(finding.get("InstalledVersion")),
                        fixed=_text(finding.get("FixedVersion")),
                    )
                )

    return findings


def markdown_text(value: str) -> str:
    """
    Escape untrusted finding metadata before placing it in Markdown.

    Args:
        value (str): Trivy-provided metadata.

    Returns:
        str: Markdown-safe text.
    """
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    for character in "\\`*_{}[]()#+-.!|":
        escaped = escaped.replace(character, f"\\{character}")

    return escaped


def markdown_code(value: str) -> str:
    """
    Escape untrusted metadata for inline code spans.

    Args:
        value (str): Trivy-provided path or package metadata.

    Returns:
        str: Safe inline code span.
    """
    escaped = value.replace("`", "'").replace("\r", " ").replace("\n", " ")
    return "`" + escaped + "`"


def render_summary(
    findings: Sequence[Finding],
    *,
    artifact_url: str = "",
    run_url: str = "",
    comment: bool = False,
    unavailable: bool = False,
) -> str:
    """
    Render a concise summary and useful links for a CI step or PR comment.

    Args:
        findings (Sequence[Finding]): Safe findings extracted from the report.
        artifact_url (str): Optional URL to the complete sanitized report artifact.
        run_url (str): Workflow URL for scan logs and report recovery.
        comment (bool): Include the PR comment marker when true.
        unavailable (bool): Indicate that no usable report was produced.

    Returns:
        str: Markdown summary.
    """
    lines: list[str] = []

    if comment:
        lines.append(COMMENT_MARKER)

    if unavailable:
        lines.extend(("### Trivy scan report unavailable", "Trivy did not produce a usable report."))
    elif not findings:
        lines.extend(("### Trivy scan: no findings", "No secret or vulnerable dependency findings were detected."))
    else:
        counts_by_kind = {kind: sum(finding.kind == kind for finding in findings) for kind in ("secret", "vulnerability")}
        severity_counts = {severity: sum(finding.severity == severity for finding in findings) for severity in SEVERITY_ORDER}
        severity_text = ", ".join(f"{severity_counts[severity]} {severity}" for severity in SEVERITY_ORDER if severity_counts[severity])
        kind_text = " and ".join(
            f"{counts_by_kind[kind]} {kind}{'s' if counts_by_kind[kind] != 1 else ''}"
            for kind in ("secret", "vulnerability")
            if counts_by_kind[kind]
        )
        lines.extend(
            (
                f"### Trivy scan: {len(findings)} finding{'s' if len(findings) != 1 else ''}",
                f"{kind_text}; severity: {severity_text}.",
            )
        )

        for finding in findings[:6]:
            location = finding.target

            if finding.line:
                location = f"{location}:{finding.line}"

            details = f"{finding.severity} {finding.kind}: {markdown_text(finding.title)}"

            if finding.kind == "vulnerability":
                details += f" ({markdown_text(finding.identifier)}"

                if finding.package:
                    details += f", {markdown_code(finding.package)}"

                if finding.installed:
                    details += f" {markdown_text(finding.installed)}"

                if finding.fixed:
                    details += f", fixed in {markdown_text(finding.fixed)}"

                details += ")"

            lines.append(f"- {markdown_code(location)}: {details}")

        if len(findings) > 6:
            lines.append(f"- Plus {len(findings) - 6} more; see the complete report.")

    if comment:
        lines.append("Secret matches and source snippets are redacted from the report.")

    links: list[str] = []

    if artifact_url:
        links.append(f"[Full scan results]({artifact_url})")

    if run_url:
        links.append(f"[Workflow logs]({run_url})")

    if links:
        lines.append(" | ".join(links))

    return "\n\n".join(lines) + "\n"


def write_outputs(path: Path, text: str) -> None:
    """
    Create a parent directory and write UTF-8 text with a trailing newline.

    Args:
        path (Path): Destination file.
        text (str): File contents.

    Returns:
        None: Destination file contains the provided text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def append_github_output(path: Path, *, available: bool, finding_count: int) -> None:
    """
    Expose report state to the final workflow gate.

    Args:
        path (Path): GitHub Actions output file.
        available (bool): Whether the JSON report was parsed and sanitized.
        finding_count (int): Number of secret and vulnerability findings, or -1 if unknown.

    Returns:
        None: Report availability and finding count are appended to the output file.
    """
    with path.open("a", encoding="utf-8") as output:
        output.write(f"available={'true' if available else 'false'}\n")
        output.write(f"finding_count={finding_count}\n")


def prepare_report(arguments: argparse.Namespace) -> int:
    """
    Sanitize Trivy output, write the job summary, and publish gate outputs.

    Args:
        arguments (argparse.Namespace): Paths and run link selected by the CLI.

    Returns:
        int: Zero when report preparation completed, including a missing report that the gate will reject.
    """
    try:
        report = load_report(arguments.input)
        sanitized = sanitize_report(report)

        if not isinstance(sanitized, dict):
            raise ValueError("Sanitized Trivy report must contain a JSON object")

        write_outputs(arguments.report_output, json.dumps(sanitized, indent=2, sort_keys=True))
        findings = collect_findings(sanitized)
        summary = render_summary(findings, run_url=arguments.run_url)
        write_outputs(arguments.summary_output, summary)

        if arguments.github_output:
            append_github_output(arguments.github_output, available=True, finding_count=len(findings))

    except (OSError, json.JSONDecodeError, ValueError):
        summary = render_summary([], run_url=arguments.run_url, unavailable=True)
        write_outputs(arguments.summary_output, summary)

        if arguments.github_output:
            append_github_output(arguments.github_output, available=False, finding_count=-1)

    return 0


def prepare_comment(arguments: argparse.Namespace) -> int:
    """
    Build a PR comment from downloaded artifact data using safe finding fields only.

    Args:
        arguments (argparse.Namespace): Artifact path and report links.

    Returns:
        int: Zero when the comment JSON file is written.
    """
    try:
        report = load_report(arguments.input)
        sanitized = sanitize_report(report)

        if not isinstance(sanitized, dict):
            raise ValueError("Sanitized Trivy report must contain a JSON object")

        findings = collect_findings(sanitized)
        body = render_summary(
            findings,
            artifact_url=arguments.artifact_url,
            run_url=arguments.run_url,
            comment=True,
        )

    except (OSError, json.JSONDecodeError, ValueError):
        body = render_summary(
            [],
            artifact_url=arguments.artifact_url,
            run_url=arguments.run_url,
            comment=True,
            unavailable=True,
        )

    payload = json.dumps({"body": body}, ensure_ascii=False)
    write_outputs(arguments.output, payload)
    return 0


def parse_arguments() -> argparse.Namespace:
    """
    Parse the report-preparation or PR-comment command.

    Returns:
        argparse.Namespace: Validated command-line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="sanitize the scanner report and create the job summary")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--report-output", type=Path, required=True)
    prepare.add_argument("--summary-output", type=Path, required=True)
    prepare.add_argument("--github-output", type=Path, default=Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None)
    prepare.add_argument("--run-url", default="")
    comment = commands.add_parser("comment", help="create a safe PR comment payload from a scan artifact")
    comment.add_argument("--input", type=Path, required=True)
    comment.add_argument("--output", type=Path, required=True)
    comment.add_argument("--artifact-url", default="")
    comment.add_argument("--run-url", default="")
    return parser.parse_args()


def main() -> int:
    """
    Execute one Trivy report operation.

    Returns:
        int: Command status.
    """
    arguments = parse_arguments()

    if arguments.command == "prepare":
        return prepare_report(arguments)

    return prepare_comment(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
