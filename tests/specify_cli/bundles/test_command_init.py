from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from specify_cli import app

runner = CliRunner()


def _make_project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    (project / ".specify").mkdir(parents=True)
    return project


def test_override_symlinked_specify_errors_bundle_init_no_fallback(
    tmp_path, monkeypatch
):
    """A symlinked override .specify must not make bundle init fall back to cwd."""
    web = tmp_path / "web"
    web.mkdir()
    real = tmp_path / "real-specify"
    real.mkdir()
    try:
        (web / ".specify").symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available in this environment")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("SPECIFY_INIT_DIR", str(web))

    result = runner.invoke(app, ["bundle", "init", "--offline"])
    assert result.exit_code != 0
    assert "symlinked .specify" in result.output
    assert not (elsewhere / ".specify").exists()


def test_bundle_init_keeps_current_release_default(project: Path):
    with patch("specify_cli.bundles.command_init.bundle_install") as install:
        result = runner.invoke(app, ["bundle", "init", "demo-bundle", "--offline"])

    assert result.exit_code == 0, result.output
    install.assert_called_once_with(
        "demo-bundle", integration=None, offline=True, version=None
    )
