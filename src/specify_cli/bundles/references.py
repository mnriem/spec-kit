"""Resolve bundle component references against real, available components.

Used by ``specify bundle validate`` (FR-005 / SC-007) to confirm that every
declared component points at something installable. Resolution is offline-first:
a reference resolves when the component is bundled with Spec Kit or already
installed in the project; catalog sources are consulted only when network access
is permitted. Offline runs that cannot confirm a reference downgrade to a
warning rather than a false failure, while definitively-unknown references
always error.
"""
from __future__ import annotations

from pathlib import Path

from .manifest import ComponentRef
from .versioning import parse_version


def _version_matches(component: ComponentRef, actual: str | None) -> bool:
    if component.version is None:
        return True
    return bool(actual) and parse_version(component.version) == parse_version(actual)


def _resolved_locally(root: Path, component: ComponentRef) -> bool:
    kind = component.kind
    try:
        from .._assets import (
            _locate_bundled_extension,
            _locate_bundled_preset,
            _locate_bundled_workflow,
        )
        from .primitives import _bundled_manifest_version, primitive_manager

        if component.source:
            return False
        if kind == "presets":
            bundled = _locate_bundled_preset(component.id)
            if bundled is not None and _version_matches(
                component, _bundled_manifest_version(bundled / "preset.yml", "preset")
            ):
                return True
        if kind == "extensions":
            bundled = _locate_bundled_extension(component.id)
            if bundled is not None and _version_matches(
                component, _bundled_manifest_version(bundled / "extension.yml", "extension")
            ):
                return True
        if kind == "workflows":
            bundled = _locate_bundled_workflow(component.id)
            if bundled is not None and _version_matches(
                component, _bundled_manifest_version(bundled / "workflow.yml", "workflow")
            ):
                return True
        if kind == "steps":
            from ..workflows import BUILTIN_STEP_TYPES

            # Step types ship with Spec Kit as built-ins (shell, gate, if, ...)
            # rather than as an on-disk asset directory, so there is no
            # ``_locate_bundled_step`` to mirror the three lookups above.
            # ``BUILTIN_STEP_TYPES`` is the bundled-with-Spec-Kit check for this
            # kind. Deliberately NOT ``STEP_REGISTRY``: ``load_custom_steps``
            # adds project-installed ids to that process-global mapping and
            # never removes them, so in a long-lived process a community step
            # loaded for one project would be accepted as "bundled" when
            # validating another. Without any bundled check at all, every
            # built-in step type looked unresolved.
            if component.id in BUILTIN_STEP_TYPES and component.version is None:
                return True
        manager = primitive_manager(kind, root, allow_network=False)
        return manager.is_installed(component) and _version_matches(
            component, manager.installed_version(component)
        )
    except Exception:  # noqa: BLE001 - resolution is best-effort
        return False
    return False


def _catalog_has_release(component: ComponentRef, get_info) -> bool:
    current = get_info(component.id)
    if current is None or not current.get("_install_allowed", True):
        return False
    if component.source and component.source != current.get("_catalog_name"):
        return False
    if component.version is None:
        return True
    if _version_matches(component, current.get("version")):
        return True
    import inspect

    if "version" not in inspect.signature(get_info).parameters:
        return False
    selected = get_info(component.id, component.version)
    return selected is not None and selected.get("_install_allowed", True)


def _resolved_in_catalog(root: Path, component: ComponentRef) -> bool | None:
    """Return True/False if a catalog could be consulted, or None on failure."""
    kind = component.kind
    try:
        if kind == "presets":
            from ..presets import PresetCatalog

            catalog = PresetCatalog(root)
            return _catalog_has_release(component, catalog.get_pack_info)
        if kind == "extensions":
            from ..extensions import ExtensionCatalog

            catalog = ExtensionCatalog(root)
            return _catalog_has_release(component, catalog.get_extension_info)
        if kind == "workflows":
            from ..workflows.catalog import WorkflowCatalog

            catalog = WorkflowCatalog(root)
            return _catalog_has_release(component, catalog.get_workflow_info)
        if kind == "steps":
            from ..workflows.catalog import StepCatalog

            catalog = StepCatalog(root)
            return _catalog_has_release(component, catalog.get_step_info)
    except Exception:  # noqa: BLE001 - catalog may be unreachable/misconfigured
        return None
    return None


def make_reference_checker(
    project_root: Path,
    *,
    allow_network: bool,
    warnings: list[str],
):
    """Build a ``ReferenceChecker`` for :func:`validate_manifest`.

    Returns an error string for a reference that is definitively unresolvable,
    ``None`` otherwise. Unverifiable references (offline, or an unreachable
    catalog) append a note to *warnings* and pass.
    """

    def check(component: ComponentRef) -> str | None:
        if _resolved_locally(project_root, component):
            return None

        if allow_network:
            in_catalog = _resolved_in_catalog(project_root, component)
            if in_catalog is True:
                return None
            if in_catalog is False:
                return (
                    f"{component.kind[:-1]} '{component.id}' at "
                    f"{component.version or 'current'} is not available from "
                    "the selected install-allowed catalog or locally."
                )
            warnings.append(
                f"Could not verify {component.kind[:-1]} '{component.id}' "
                "(catalog unreachable); reference left unchecked."
            )
            return None

        warnings.append(
            f"Could not verify {component.kind[:-1]} '{component.id}' offline "
            "(not bundled or installed); re-run validate online to check catalogs."
        )
        return None

    return check
