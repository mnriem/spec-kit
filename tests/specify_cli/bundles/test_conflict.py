"""Unit tests for conflict detection (T034): integration clash and overlap precedence."""
from __future__ import annotations

from specify_cli.bundles.manifest import BundleManifest, ComponentRef
from specify_cli.bundles.records import InstalledBundleRecord
from specify_cli.bundles.conflict import detect_conflicts
from specify_cli.bundles._commands import _bundle_overlaps
from specify_cli.bundles.records import save_records
from tests.specify_cli.bundles.helpers import make_project, valid_manifest_dict


def _manifest(**overrides) -> BundleManifest:
    return BundleManifest.from_dict(valid_manifest_dict(**overrides))


def test_integration_clash_is_blocking():
    manifest = _manifest(integration={"id": "claude"})
    report = detect_conflicts(manifest, active_integration="copilot", installed=[])
    assert report.has_blocking_conflict is True
    assert "claude" in report.integration_clash
    assert "copilot" in report.integration_clash


def test_matching_integration_no_clash():
    manifest = _manifest(integration={"id": "copilot"})
    report = detect_conflicts(manifest, active_integration="copilot", installed=[])
    assert report.has_blocking_conflict is False


def test_agnostic_bundle_never_clashes():
    manifest = _manifest()  # no integration
    report = detect_conflicts(manifest, active_integration="copilot", installed=[])
    assert report.has_blocking_conflict is False


def test_overlap_with_other_bundle_is_reported():
    manifest = _manifest()
    other = InstalledBundleRecord.create(
        bundle_id="other",
        version="1.0.0",
        components=[ComponentRef(kind="presets", id="preset-a", version="2.0.0")],
    )
    report = detect_conflicts(manifest, active_integration="copilot", installed=[other])
    assert any("preset-a" in o and "other" in o for o in report.overlaps)
    assert report.has_blocking_conflict is False


def test_same_bundle_reinstall_is_not_overlap():
    manifest = _manifest()
    same = InstalledBundleRecord.create(
        bundle_id="demo-bundle",
        version="1.2.0",
        components=[ComponentRef(kind="presets", id="preset-a")],
    )
    report = detect_conflicts(manifest, active_integration="copilot", installed=[same])
    assert report.overlaps == []


def test_different_pin_from_another_bundle_is_blocking():
    manifest = _manifest()
    other = InstalledBundleRecord.create(
        bundle_id="other",
        version="1.0.0",
        components=[ComponentRef(kind="presets", id="preset-a", version="3.0.0")],
    )

    report = detect_conflicts(manifest, active_integration="copilot", installed=[other])

    assert report.has_blocking_conflict
    assert "preset-a" in report.version_clashes[0]
    assert "2.0.0" in report.version_clashes[0]
    assert "3.0.0" in report.version_clashes[0]
    assert report.overlaps == []


def test_equivalent_pin_from_another_bundle_is_shareable():
    manifest = _manifest()
    other = InstalledBundleRecord.create(
        bundle_id="other",
        version="1.0.0",
        components=[ComponentRef(kind="presets", id="preset-a", version="v2.0.0")],
    )

    report = detect_conflicts(manifest, active_integration="copilot", installed=[other])

    assert not report.has_blocking_conflict
    assert report.version_clashes == []
    assert len(report.overlaps) == 1


def test_unknown_pin_from_another_bundle_cannot_satisfy_exact_pin():
    manifest = _manifest()
    other = InstalledBundleRecord.create(
        bundle_id="other",
        version="1.0.0",
        components=[ComponentRef(kind="presets", id="preset-a")],
    )

    report = detect_conflicts(manifest, active_integration="copilot", installed=[other])

    assert report.has_blocking_conflict
    assert "<unknown>" in report.version_clashes[0]


def test_info_preview_reports_version_conflict(tmp_path):
    make_project(tmp_path)
    other = InstalledBundleRecord.create(
        bundle_id="other",
        version="1.0.0",
        components=[ComponentRef(kind="presets", id="preset-a", version="3.0.0")],
    )
    save_records(tmp_path, [other])

    overlaps = _bundle_overlaps(tmp_path, _manifest(), offline=True)

    assert len(overlaps) == 1
    assert "Only one version" in overlaps[0]
