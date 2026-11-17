"""Tests of the worker health report and CLI."""
import datetime
import json

import pytest

from filetag_providers import ProfileRegistry
from filetag_worker.cli import WorkerCli, main
from filetag_worker.health import Health


def test_health_reports_missing_programs():
    """Without ffmpeg the worker is not ready."""
    report = Health(which=lambda name: None).report()
    assert report["ok"] is False and report["protocol"] == 1
    assert Health(which=lambda name: f"/usr/bin/{name}").report()["ok"] is True


def test_cli_health(capsys: pytest.CaptureFixture[str]) -> None:
    """The health sub-command prints JSON and sets the exit code.

    Args:
        capsys: pytest fixture capturing output.
    """
    cli = WorkerCli(health=Health(which=lambda name: "/bin/" + name))
    assert cli.run(["health"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert WorkerCli(health=Health(which=lambda name: None)).run(["health"]) == 1


def test_cli_providers_marks_stale_profiles(capsys: pytest.CaptureFixture[str]) -> None:
    """Profiles older than the limit are marked and change the exit code.

    Args:
        capsys: pytest fixture capturing output.
    """
    registry = ProfileRegistry.builtin()
    fresh = WorkerCli(registry=registry, today=datetime.date(2026, 11, 20))
    assert fresh.run(["providers"]) == 0
    assert "anthropic" in capsys.readouterr().out
    late = WorkerCli(registry=registry, today=datetime.date(2027, 6, 1))
    assert late.run(["providers"]) == 1
    assert "STALE" in capsys.readouterr().out


def test_main(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """main reads sys.argv.

    Args:
        capsys: pytest fixture capturing output.
        monkeypatch: pytest fixture replacing sys.argv.
    """
    monkeypatch.setattr("sys.argv", ["filetag-worker", "providers"])
    assert main() in (0, 1)
    assert "ollama" in capsys.readouterr().out
