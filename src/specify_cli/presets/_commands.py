"""Shared infrastructure and registration for ``specify preset`` commands.

Command handlers belong in ``command_*.py`` modules. Thin compatibility
forwarders preserve established direct-import and monkeypatch paths.
"""

from __future__ import annotations

import typer

from .._download_security import read_response_limited as read_response_limited

preset_app = typer.Typer(
    name="preset",
    help="Manage spec-kit presets",
    add_completion=False,
)


def _warn_unmet_extension_dependencies(*args, **kwargs):
    """Forward calls to the add command's dependency warning helper."""
    from .command_add import _warn_unmet_extension_dependencies as _helper

    return _helper(*args, **kwargs)


def preset_add(*args, **kwargs):
    """Forward direct calls to the extracted add command handler."""
    from .command_add import preset_add as _preset_add

    return _preset_add(*args, **kwargs)


def register(app: typer.Typer) -> None:
    """Attach the preset command group to the root Typer app."""
    from .catalog import register as register_catalog

    register_catalog(preset_app)

    # isort: off
    from . import command_list  # noqa: F401 — registers handler via decorator
    from . import command_add  # noqa: F401 — registers handler via decorator
    from . import command_remove  # noqa: F401 — registers handler via decorator
    from . import command_search  # noqa: F401 — registers handler via decorator
    from . import command_resolve  # noqa: F401 — registers handler via decorator
    from . import command_info  # noqa: F401 — registers handler via decorator
    from . import command_set_priority  # noqa: F401 — registers handler via decorator
    from . import command_enable  # noqa: F401 — registers handler via decorator
    from . import command_disable  # noqa: F401 — registers handler via decorator
    # isort: on

    app.add_typer(preset_app, name="preset")
