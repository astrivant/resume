"""
Exercise awareness authorization, bundle integrity, figure filtering, and compiler integration offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image

from resumeme.awareness.bundle import stage_figures, validate_bundle
from resumeme.awareness.dispatch import receive
from resumeme.awareness.models import FIGURES, Appendices, Awareness, AwarenessAppendix, FigureSelector, selected_figures
from resumeme.compiler.asts.profile import Profile
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, company_config, load_config
from resumeme.config.models import CompanyTarget
from resumeme.exceptions import PublicationError, RenderingError

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def _bundle(*keys: str) -> bytes:
    """
    Encode tiny synthetic figures with real PNG bytes and content hashes.

    Args:
        *keys (str): Catalog figure identifiers to include.

    Returns:
        bytes: Valid version-one JSON transport.
    """
    stream = BytesIO()
    Image.new("RGB", (80, 40), "white").save(stream, format="PNG")
    image = stream.getvalue()
    return json.dumps(
        {
            "version": 1,
            "figures": [
                {
                    "id": key,
                    "group": FIGURES[key],
                    "title": "Evidence & observations",
                    "sha256": hashlib.sha256(image).hexdigest(),
                    "png": base64.b64encode(image).decode(),
                }
                for key in keys
            ],
        }
    ).encode()


def _config() -> Config:
    """
    Enable one figure and one synthetic sender without changing repository defaults.

    Returns:
        Config: Explicit opt-in fixture configuration.
    """
    return Config(
        LinkedIn("example-person"),
        awareness=Awareness(True, ("example-bot",)),
        appendices=Appendices(AwarenessAppendix({"knowledge-usage": True})),
    )


def test_filters_are_opt_in_and_exclusion_wins() -> None:
    """
    Keep visibility independent from selectors and support category-only filters.

    Returns:
        None: Missing switches stay disabled, any-field selectors work, and order survives.
    """
    assert selected_figures(AwarenessAppendix()) == ()
    settings = AwarenessAppendix(
        {"toolbox-use": True, "knowledge-map": True, "knowledge-usage": True, "knowledge-hierarchy": False},
        include=(FigureSelector(group="knowledge"),),
        exclude=(FigureSelector(id="knowledge-map"),),
    )
    assert selected_figures(settings) == ("knowledge-usage",)
    assert selected_figures(evolve(settings, include=(FigureSelector(id="toolbox-use", group="knowledge"),))) == ()


@pytest.mark.parametrize("fault", ["hash", "duplicate", "group", "version", "extra", "path", "not-png"])
def test_bundle_rejects_untrusted_inputs(fault: str) -> None:
    """
    Fail malformed bundles before rendering or staging their images.

    Args:
        fault (str): Independent contract or raster violation.

    Returns:
        None: All corruptions fail closed with a schema or image error.
    """
    data = json.loads(_bundle("knowledge-usage"))
    figure = data["figures"][0]

    if fault == "hash":
        figure["sha256"] = "0" * 64
    elif fault == "duplicate":
        data["figures"].append(figure.copy())
    elif fault == "group":
        figure["group"] = "checkpoints"
    elif fault == "version":
        data["version"] = 2
    elif fault == "extra":
        data["journal"] = "unwanted source data"
    elif fault == "path":
        figure["id"] = "../../resume"
    elif fault == "not-png":
        figure["png"] = base64.b64encode(b"not a PNG").decode()
        figure["sha256"] = hashlib.sha256(b"not a PNG").hexdigest()

    with pytest.raises((RenderingError, ValidationError)):
        validate_bundle(json.dumps(data).encode())


def test_disabled_appendix_does_not_read_data(tmp_path: Path) -> None:
    """
    Preserve existing resumes when the integration is absent or disabled.

    Args:
        tmp_path (Path): Empty compiler root.

    Returns:
        None: Disabled settings need no files; explicit missing selections fail.
    """
    assert stage_figures(Config(LinkedIn("example-person")), tmp_path, tmp_path) == []

    with pytest.raises(RenderingError, match="require data"):
        stage_figures(_config(), tmp_path, tmp_path)


def test_receive_and_render_exact_bundle(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Carry validated dispatch data through the real renderer without remote services.

    Args:
        tmp_path (Path): Trusted checkout fixture.
        monkeypatch (MonkeyPatch): GitHub request replacement.

    Returns:
        None: Selected figures appear after body content, with escaped captions and first-page navigation.
    """
    bundle = _bundle("knowledge-usage", "knowledge-map")
    event = {
        "action": "witful-awareness",
        "sender": {"login": "example-bot"},
        "client_payload": {"version": 1, "commit": "a" * 40, "sha256": hashlib.sha256(bundle).hexdigest()},
    }

    def download(command: list[str], **kwargs: object) -> CompletedProcess[bytes]:
        """
        Verify the fixed host and immutable path before returning synthetic image data.

        Args:
            command (list[str]): gh request arguments.
            **kwargs (object): Subprocess execution options.

        Returns:
            CompletedProcess[bytes]: Successful bounded GitHub response.
        """
        assert command[:4] == ["gh", "api", "--hostname", "github.com"]
        assert command[4] == "repos/example/resume/contents/awareness.json?ref=" + "a" * 40
        return CompletedProcess(command, 0, bundle, b"")

    monkeypatch.setattr("resumeme.awareness.dispatch.subprocess.run", download)
    config = _config()
    receive(config, tmp_path, event, "example/resume", "example-bot")
    assert (tmp_path / "data/awareness.json").read_bytes() == bundle
    profile = Profile(username="example-person", name="Example Person")
    source = render_profile(profile, config, tmp_path).read_text()
    assert r"\hyperlink{awareness-knowledge-usage}" in source
    assert r"\hypertarget{awareness-knowledge-usage}" in source
    assert "knowledge-map.png" not in source
    assert r"Evidence \& observations" in source
    assert r"\finishthispage" in source

    # A valid sender cannot replace the last accepted input with a corrupted or mismatched bundle.
    event = json.loads(json.dumps(event))
    event["client_payload"]["sha256"] = "0" * 64
    with pytest.raises(PublicationError, match="SHA-256"):
        receive(config, tmp_path, event, "example/resume", "example-bot")
    assert (tmp_path / "data/awareness.json").read_bytes() == bundle


@pytest.mark.parametrize("enabled,actor", [(False, "example-bot"), (True, "unlisted")])
def test_unauthorized_dispatch_never_downloads(tmp_path: Path, monkeypatch: MonkeyPatch, enabled: bool, actor: str) -> None:
    """
    Require the receiver's own opt-in and authenticated sender allowlist before network access.

    Args:
        tmp_path (Path): Isolated checkout.
        monkeypatch (MonkeyPatch): Network guard.
        enabled (bool): Receiver switch.
        actor (str): Authenticated GitHub actor.

    Returns:
        None: Rejected requests cannot read data or write accepted input.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        """
        Fail any unexpected provider call.

        Args:
            *args (object): Unexpected arguments.
            **kwargs (object): Unexpected execution options.

        Returns:
            None: Always raises an assertion.
        """
        pytest.fail("An unauthorized dispatch reached GitHub")

    monkeypatch.setattr("resumeme.awareness.dispatch.subprocess.run", forbidden)
    config = evolve(_config(), awareness=Awareness(enabled, ("example-bot",)))
    with pytest.raises(PublicationError, match="requires"):
        receive(config, tmp_path, {}, "example/resume", actor)
    assert not (tmp_path / "data/awareness.json").exists()


def test_grouped_config_roundtrip_and_job_override(tmp_path: Path) -> None:
    """
    Validate the public hierarchy, reject unknown figures, and preserve sparse employer overrides.

    Args:
        tmp_path (Path): Configuration fixture directory.

    Returns:
        None: Typed settings reflect per-job visibility without changing the base config.
    """
    path = tmp_path / "resumeme.config.yaml"
    data = {
        "profile": {"linkedin": {"username": "example-person"}},
        "document": {"appendices": {"awareness": {"figures": {"knowledge-usage": True}, "exclude": [{"group": "checkpoints"}]}}},
    }
    path.write_text(yaml.safe_dump(data))
    config = load_config(path)
    assert selected_figures(config.appendices.awareness) == ("knowledge-usage",)
    target = CompanyTarget(
        "example",
        "https://www.linkedin.com/jobs/view/123/",
        overrides={"document": {"appendices": {"awareness": {"figures": {"knowledge-usage": False}}}}},
    )
    assert selected_figures(company_config(config, target, root=tmp_path).appendices.awareness) == ()
    path.write_text(path.read_text().replace("knowledge-usage", "unknown-figure"))
    with pytest.raises(ValidationError):
        load_config(path)


def test_workflow_uses_main_code_and_one_dispatch_pipeline() -> None:
    """
    Keep transport pushes out of CI and require validated artifacts before both document consumers.

    Returns:
        None: Workflow topology retains the default-branch trust boundary and shared publication path.
    """
    root = Path(__file__).resolve().parents[4]
    pipeline = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    trigger = pipeline[True]
    assert trigger["repository_dispatch"]["types"] == ["witful-awareness"]
    assert "!witful-awareness" in trigger["push"]["branches"]
    for job in ("documents-stage", "resume-stage", "verified"):
        assert "awareness" in pipeline["jobs"][job]["needs"]
    checkout = pipeline["jobs"]["awareness"]["steps"][0]
    assert checkout["with"]["ref"] == "${{ needs.source.outputs.sha }}"
    for name in ("stage-resume.yml", "stage-documents.yml"):
        assert "name: awareness-figures" in (root / ".github/workflows" / name).read_text()


def test_decision_figure_config_bundle_and_render(tmp_path: Path) -> None:
    """
    Accept the Life figure through the public schema, selection rules, and LaTeX compiler.

    Args:
        tmp_path (Path): Isolated receiver with a two-figure bundle.

    Returns:
        None: Both enabled figures render in order; a life-only filter selects the decisions chart.
    """
    path = tmp_path / "resumeme.config.yaml"
    settings = {
        "profile": {"linkedin": {"username": "example-person"}},
        "document": {"appendices": {"awareness": {"figures": {"knowledge-map": True, "decision-influences": True}}}},
    }
    path.write_text(yaml.safe_dump(settings, sort_keys=False))
    config = load_config(path)
    bundle = _bundle("knowledge-map", "decision-influences")
    validate_bundle(bundle)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/awareness.json").write_bytes(bundle)
    source = render_profile(Profile(username="example-person", name="Example Person"), config, tmp_path).read_text()
    assert source.index(r"\hypertarget{awareness-knowledge-map}") < source.index(r"\hypertarget{awareness-decision-influences}")
    appendix = evolve(config.appendices.awareness, include=(FigureSelector(group="life"),))
    assert selected_figures(appendix) == ("decision-influences",)
    assert selected_figures(evolve(appendix, exclude=(FigureSelector(group="life"),))) == ()
