"""Structured installation-provenance metadata shared by the registries.

Both :class:`~specify_cli.extensions.ExtensionRegistry` and
:class:`~specify_cli.presets.PresetRegistry` record how an installed package
entered the project. Historically this was a flat ``"source": "local"`` string
written for *every* install — including catalog downloads — which erased the
distinction between local-directory, catalog, and bundled installations.

This module defines a single ``SourceInfo`` shape and the shared
validate/normalize helpers both registries use, so the two implementations
cannot drift apart.

Schema::

    {
        "kind": "catalog" | "local" | "builtin" | "git",
        "catalog": "<catalog-name>",   # catalog kind
        "path": "<absolute-path>",     # local kind
        "url": "<git-url>",            # git kind
        "ref": "<sha-or-ref>",         # git kind (optional)
    }

Field requirements for **new writes** (:func:`validate_source`):

- ``kind: "local"`` requires an absolute ``path``.
- ``kind: "catalog"`` requires a non-empty ``catalog`` name.
- ``kind: "builtin"`` has no additional required fields.
- ``kind: "git"`` is schema-only and forward-compatible: it requires a ``url``
  and may carry a ``ref``. No git-install producer ships today.

Legacy values are tolerated only on **read** (:func:`normalize_source`), which
maps them to the structured shape *without* rewriting registry files::

    missing / None  -> {"kind": "local"}
    "local"          -> {"kind": "local"}
    "catalog"        -> {"kind": "catalog", "catalog": None}
    structured dict  -> validated leniently and returned

``{"kind": "catalog", "catalog": None}`` is a legacy-only read sentinel: new
writes reject it.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Optional

try:  # TypedDict is only used for type hints and is optional at runtime.
    from typing import TypedDict

    class SourceInfo(TypedDict, total=False):
        """Structured installation-provenance record. See module docstring."""

        kind: str
        catalog: Optional[str]
        path: str
        url: str
        ref: str
except Exception:  # pragma: no cover - defensive for exotic runtimes
    SourceInfo = dict  # type: ignore[assignment,misc]


# Recognized source kinds.
VALID_KINDS = ("catalog", "local", "builtin", "git")

# Fields permitted for each kind, in addition to the mandatory ``kind`` key.
# Anything outside this set is rejected on write and dropped on read.
_ALLOWED_FIELDS: dict[str, frozenset] = {
    "local": frozenset({"path"}),
    "catalog": frozenset({"catalog"}),
    "builtin": frozenset(),
    "git": frozenset({"url", "ref"}),
}


class SourceValidationError(ValueError):
    """Raised when a source value is invalid for persistence."""


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def validate_source(raw: Any) -> SourceInfo:
    """Validate a source value destined for the registry.

    Enforces the strict, write-time schema described in the module docstring
    and returns a defensive deep copy containing only the recognized fields for
    the given kind. Raises :class:`SourceValidationError` for anything invalid.

    New writes must not use the legacy ``{"kind": "catalog", "catalog": None}``
    read sentinel — a catalog source must name its catalog.
    """
    if not isinstance(raw, dict):
        raise SourceValidationError(
            f"source must be a mapping, got {type(raw).__name__}"
        )

    kind = raw.get("kind")
    if kind not in VALID_KINDS:
        raise SourceValidationError(
            f"source kind must be one of {VALID_KINDS}, got {kind!r}"
        )

    allowed = _ALLOWED_FIELDS[kind]
    extra = set(raw) - {"kind"} - allowed
    if extra:
        raise SourceValidationError(
            f"source kind {kind!r} does not allow field(s): "
            f"{', '.join(sorted(extra))}"
        )

    result: dict[str, Any] = {"kind": kind}

    if kind == "local":
        path = raw.get("path")
        if not _is_nonempty_str(path):
            raise SourceValidationError(
                "source kind 'local' requires a non-empty 'path'"
            )
        if not os.path.isabs(path):
            raise SourceValidationError(
                f"source kind 'local' requires an absolute 'path', got {path!r}"
            )
        result["path"] = path
    elif kind == "catalog":
        catalog = raw.get("catalog")
        if not _is_nonempty_str(catalog):
            raise SourceValidationError(
                "source kind 'catalog' requires a non-empty 'catalog' name"
            )
        result["catalog"] = catalog
    elif kind == "git":
        url = raw.get("url")
        if not _is_nonempty_str(url):
            raise SourceValidationError(
                "source kind 'git' requires a non-empty 'url'"
            )
        result["url"] = url
        if "ref" in raw:
            ref = raw.get("ref")
            if not _is_nonempty_str(ref):
                raise SourceValidationError(
                    "source kind 'git' 'ref' must be a non-empty string when present"
                )
            result["ref"] = ref
    # builtin: nothing beyond kind.

    return copy.deepcopy(result)


def normalize_source(raw: Any) -> SourceInfo:
    """Normalize a stored/legacy source value for read APIs.

    Lenient by design: reads must never crash on legacy or slightly malformed
    data. Returns a freshly built structured dict; existing registry files are
    never rewritten as a side effect.
    """
    if raw is None:
        return {"kind": "local"}

    if isinstance(raw, str):
        if raw == "local":
            return {"kind": "local"}
        if raw == "catalog":
            # Legacy flat "catalog" string never identified the catalog.
            return {"kind": "catalog", "catalog": None}
        # Any other legacy string (e.g. "dev", a path, "core") predates the
        # structured schema and cannot be mapped reliably; treat as local.
        return {"kind": "local"}

    if isinstance(raw, dict):
        kind = raw.get("kind")
        if kind not in VALID_KINDS:
            return {"kind": "local"}

        result: dict[str, Any] = {"kind": kind}
        if kind == "local":
            path = raw.get("path")
            if _is_nonempty_str(path):
                result["path"] = path
        elif kind == "catalog":
            catalog = raw.get("catalog")
            # Preserve the legacy None sentinel; otherwise keep a valid name.
            result["catalog"] = catalog if _is_nonempty_str(catalog) else None
        elif kind == "git":
            url = raw.get("url")
            if _is_nonempty_str(url):
                result["url"] = url
            ref = raw.get("ref")
            if _is_nonempty_str(ref):
                result["ref"] = ref
        # builtin: kind only.
        return result

    # Any other type (list, int, ...) is unrecognized legacy data.
    return {"kind": "local"}


# --- Convenience constructors for call sites --------------------------------


def local_source(path: os.PathLike | str) -> SourceInfo:
    """Build a validated ``local`` source from an absolute path."""
    return validate_source({"kind": "local", "path": str(path)})


def catalog_source(catalog_name: str) -> SourceInfo:
    """Build a validated ``catalog`` source naming its catalog."""
    return validate_source({"kind": "catalog", "catalog": catalog_name})


def builtin_source() -> SourceInfo:
    """Build a validated ``builtin`` source."""
    return validate_source({"kind": "builtin"})


def git_source(url: str, ref: Optional[str] = None) -> SourceInfo:
    """Build a validated ``git`` source. Schema-only; no producer ships today."""
    raw: dict[str, Any] = {"kind": "git", "url": url}
    if ref is not None:
        raw["ref"] = ref
    return validate_source(raw)
