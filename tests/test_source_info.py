"""Tests for structured installation-provenance metadata (``_source_info``).

Covers the shared schema helpers plus the extension/preset registry and
manager round trips: default source-path behavior, legacy normalization,
defensive copies, invalid source rejection, catalog installs through the
command-level path, force reinstall, and registry restore/update.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from specify_cli._source_info import (
    SourceValidationError,
    builtin_source,
    catalog_source,
    git_source,
    local_source,
    normalize_source,
    validate_source,
)


# ===== Shared module unit tests =====


class TestValidateSource:
    def test_local_requires_absolute_path(self):
        assert validate_source({"kind": "local", "path": "/abs/x"}) == {
            "kind": "local",
            "path": "/abs/x",
        }
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "local", "path": "relative/x"})
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "local"})

    def test_catalog_requires_name(self):
        assert validate_source({"kind": "catalog", "catalog": "community"}) == {
            "kind": "catalog",
            "catalog": "community",
        }
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "catalog"})

    def test_catalog_null_sentinel_rejected_on_write(self):
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "catalog", "catalog": None})

    def test_builtin_has_no_extra_fields(self):
        assert validate_source({"kind": "builtin"}) == {"kind": "builtin"}
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "builtin", "path": "/x"})

    def test_git_is_schema_only(self):
        assert validate_source({"kind": "git", "url": "https://h/r.git"}) == {
            "kind": "git",
            "url": "https://h/r.git",
        }
        assert validate_source(
            {"kind": "git", "url": "https://h/r.git", "ref": "abc"}
        ) == {"kind": "git", "url": "https://h/r.git", "ref": "abc"}
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "git"})

    def test_unknown_kind_rejected(self):
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "nope"})

    def test_unknown_field_rejected(self):
        with pytest.raises(SourceValidationError):
            validate_source({"kind": "local", "path": "/x", "extra": 1})

    def test_non_mapping_rejected(self):
        for bad in ("local", None, ["local"], 3):
            with pytest.raises(SourceValidationError):
                validate_source(bad)

    def test_returns_defensive_copy(self):
        raw = {"kind": "local", "path": "/x"}
        out = validate_source(raw)
        out["path"] = "/mutated"
        assert raw["path"] == "/x"


class TestNormalizeSource:
    def test_missing_and_none(self):
        assert normalize_source(None) == {"kind": "local"}

    def test_legacy_local_string(self):
        assert normalize_source("local") == {"kind": "local"}

    def test_legacy_catalog_string_yields_null_sentinel(self):
        assert normalize_source("catalog") == {"kind": "catalog", "catalog": None}

    def test_unknown_legacy_string_falls_back_to_local(self):
        assert normalize_source("dev") == {"kind": "local"}
        assert normalize_source("/some/path") == {"kind": "local"}

    def test_structured_local_preserved(self):
        assert normalize_source({"kind": "local", "path": "/x"}) == {
            "kind": "local",
            "path": "/x",
        }

    def test_structured_catalog_preserved(self):
        assert normalize_source({"kind": "catalog", "catalog": "cat"}) == {
            "kind": "catalog",
            "catalog": "cat",
        }

    def test_structured_catalog_null_read_sentinel_preserved(self):
        assert normalize_source({"kind": "catalog", "catalog": None}) == {
            "kind": "catalog",
            "catalog": None,
        }

    def test_malformed_dict_falls_back_to_local(self):
        assert normalize_source({"kind": "bogus"}) == {"kind": "local"}
        assert normalize_source({}) == {"kind": "local"}

    def test_non_string_non_dict_falls_back_to_local(self):
        assert normalize_source(42) == {"kind": "local"}
        assert normalize_source(["x"]) == {"kind": "local"}


class TestBuilders:
    def test_local_source(self):
        assert local_source("/abs/p") == {"kind": "local", "path": "/abs/p"}

    def test_catalog_source(self):
        assert catalog_source("cat") == {"kind": "catalog", "catalog": "cat"}

    def test_builtin_source(self):
        assert builtin_source() == {"kind": "builtin"}

    def test_git_source(self):
        assert git_source("https://h/r.git") == {
            "kind": "git",
            "url": "https://h/r.git",
        }
        assert git_source("https://h/r.git", "abc") == {
            "kind": "git",
            "url": "https://h/r.git",
            "ref": "abc",
        }


# ===== Manager-level fixtures =====


@pytest.fixture
def temp_dir():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_extension_source(root: Path, ext_id: str = "prov-ext", version: str = "1.0.0") -> Path:
    ext_dir = root / ext_id
    ext_dir.mkdir()
    manifest = {
        "schema_version": "1.0",
        "extension": {
            "id": ext_id,
            "name": "Provenance Ext",
            "version": version,
            "description": "d",
            "author": "a",
            "repository": "https://github.com/x/y",
            "license": "MIT",
        },
        "requires": {"speckit_version": ">=0.1.0"},
        "provides": {
            "commands": [
                {
                    "name": f"speckit.{ext_id}.hello",
                    "file": "commands/hello.md",
                    "description": "c",
                }
            ]
        },
    }
    (ext_dir / "extension.yml").write_text(yaml.dump(manifest))
    (ext_dir / "commands").mkdir()
    (ext_dir / "commands" / "hello.md").write_text(
        "---\ndescription: h\n---\n\n$ARGUMENTS\n"
    )
    return ext_dir


def _make_preset_source(root: Path, pack_id: str = "prov-pack", version: str = "1.0.0") -> Path:
    pack_dir = root / pack_id
    pack_dir.mkdir()
    manifest = {
        "schema_version": "1.0",
        "preset": {
            "id": pack_id,
            "name": "Provenance Pack",
            "version": version,
            "description": "d",
            "author": "a",
            "repository": "https://github.com/x/y",
            "license": "MIT",
        },
        "requires": {"speckit_version": ">=0.1.0"},
        "provides": {
            "templates": [
                {
                    "type": "template",
                    "name": "spec-template",
                    "file": "templates/spec-template.md",
                    "description": "c",
                    "replaces": "spec-template",
                }
            ]
        },
    }
    (pack_dir / "preset.yml").write_text(yaml.dump(manifest))
    (pack_dir / "templates").mkdir()
    (pack_dir / "templates" / "spec-template.md").write_text("# T\n")
    return pack_dir


def _project(root: Path) -> Path:
    proj = root / "project"
    proj.mkdir()
    (proj / ".specify").mkdir()
    return proj


# ===== Extension manager round trips =====


class TestExtensionProvenance:
    def test_default_source_is_local_resolved_source_dir(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(src, "0.1.0", register_commands=False)

        meta = manager.registry.get("prov-ext")
        assert meta["source"] == {"kind": "local", "path": str(src.resolve())}
        # Not the install destination under .specify.
        assert ".specify" not in meta["source"]["path"]

    def test_explicit_builtin_source(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(
            src, "0.1.0", register_commands=False, source=builtin_source()
        )
        assert manager.registry.get("prov-ext")["source"] == {"kind": "builtin"}

    def test_explicit_catalog_source(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(
            src, "0.1.0", register_commands=False, source=catalog_source("community")
        )
        assert manager.registry.get("prov-ext")["source"] == {
            "kind": "catalog",
            "catalog": "community",
        }

    def test_invalid_source_rejected(self, temp_dir):
        from specify_cli.extensions import ExtensionManager, ValidationError

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        with pytest.raises(ValidationError):
            manager.install_from_directory(
                src, "0.1.0", register_commands=False, source={"kind": "bogus"}
            )
        assert not manager.registry.is_installed("prov-ext")

    def test_force_reinstall_updates_source(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(
            src, "0.1.0", register_commands=False, source=catalog_source("community")
        )
        # Reinstall from a bundled source with --force.
        manager.install_from_directory(
            src, "0.1.0", register_commands=False, force=True, source=builtin_source()
        )
        assert manager.registry.get("prov-ext")["source"] == {"kind": "builtin"}

    def test_legacy_string_normalized_on_read(self, temp_dir):
        from specify_cli.extensions import ExtensionRegistry

        ext_dir = temp_dir / "extensions"
        ext_dir.mkdir()
        registry = ExtensionRegistry(ext_dir)
        # Simulate a legacy registry entry written by an older Spec Kit.
        registry.data["extensions"]["legacy"] = {
            "version": "1.0.0",
            "source": "local",
        }
        registry._save()

        reloaded = ExtensionRegistry(ext_dir)
        assert reloaded.get("legacy")["source"] == {"kind": "local"}
        assert reloaded.list()["legacy"]["source"] == {"kind": "local"}
        # The registry file itself is not rewritten by a read.
        assert reloaded.data["extensions"]["legacy"]["source"] == "local"

    def test_get_returns_defensive_copy_of_source(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(src, "0.1.0", register_commands=False)

        meta = manager.registry.get("prov-ext")
        meta["source"]["path"] = "/mutated"
        assert manager.registry.get("prov-ext")["source"]["path"] != "/mutated"

    def test_restore_and_update_preserve_source(self, temp_dir):
        from specify_cli.extensions import ExtensionManager

        proj = _project(temp_dir)
        src = _make_extension_source(temp_dir)
        manager = ExtensionManager(proj)
        manager.install_from_directory(
            src, "0.1.0", register_commands=False, source=catalog_source("community")
        )
        backup = manager.registry.get("prov-ext")

        manager.registry.update("prov-ext", {"enabled": False})
        assert manager.registry.get("prov-ext")["source"] == {
            "kind": "catalog",
            "catalog": "community",
        }

        manager.registry.restore("prov-ext", backup)
        assert manager.registry.get("prov-ext")["source"] == {
            "kind": "catalog",
            "catalog": "community",
        }


# ===== Preset manager round trips =====


class TestPresetProvenance:
    def test_default_source_is_local_resolved_source_dir(self, temp_dir):
        from specify_cli.presets import PresetManager

        proj = _project(temp_dir)
        src = _make_preset_source(temp_dir)
        manager = PresetManager(proj)
        manager.install_from_directory(src, "0.1.0")

        meta = manager.registry.get("prov-pack")
        assert meta["source"] == {"kind": "local", "path": str(src.resolve())}

    def test_explicit_builtin_and_catalog(self, temp_dir):
        from specify_cli.presets import PresetManager

        proj = _project(temp_dir)
        manager = PresetManager(proj)

        src1 = _make_preset_source(temp_dir, "pack-builtin")
        manager.install_from_directory(src1, "0.1.0", source=builtin_source())
        assert manager.registry.get("pack-builtin")["source"] == {"kind": "builtin"}

        src2 = _make_preset_source(temp_dir, "pack-catalog")
        manager.install_from_directory(src2, "0.1.0", source=catalog_source("community"))
        assert manager.registry.get("pack-catalog")["source"] == {
            "kind": "catalog",
            "catalog": "community",
        }

    def test_invalid_source_rejected(self, temp_dir):
        from specify_cli.presets import PresetManager, PresetValidationError

        proj = _project(temp_dir)
        src = _make_preset_source(temp_dir)
        manager = PresetManager(proj)
        with pytest.raises(PresetValidationError):
            manager.install_from_directory(src, "0.1.0", source={"kind": "catalog"})
        assert not manager.registry.is_installed("prov-pack")

    def test_legacy_string_normalized_on_read(self, temp_dir):
        from specify_cli.presets import PresetRegistry

        packs_dir = temp_dir / "presets"
        packs_dir.mkdir()
        registry = PresetRegistry(packs_dir)
        registry.data["presets"]["legacy"] = {"version": "1.0.0", "source": "catalog"}
        registry._save()

        reloaded = PresetRegistry(packs_dir)
        assert reloaded.get("legacy")["source"] == {"kind": "catalog", "catalog": None}
        assert reloaded.list()["legacy"]["source"] == {
            "kind": "catalog",
            "catalog": None,
        }
        assert reloaded.data["presets"]["legacy"]["source"] == "catalog"
