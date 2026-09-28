"""Integration tests for the catalog stack: precedence, policy gating, search."""

from __future__ import annotations


import pytest

from specify_cli.bundler import BundlerError
from specify_cli.bundles.catalogs import (
    CatalogSource,
    InstallPolicy,
    Scope,
    load_catalog_payload,
)
from specify_cli.bundles.catalog_stack import CatalogStack
from tests.specify_cli.bundles.helpers import catalog_entry_dict, catalog_payload


def _source(source_id, priority, policy, url="builtin://x"):
    return CatalogSource(
        id=source_id,
        url=url,
        priority=priority,
        install_policy=InstallPolicy(policy),
        scope=Scope.PROJECT,
    )


def _stack(sources, payloads):
    def fetcher(src):
        return payloads[src.id]

    return CatalogStack(sources, fetcher)


def test_resolve_prefers_highest_precedence_source():
    sources = [
        _source("low", 2, "install-allowed"),
        _source("high", 1, "discovery-only"),
    ]
    payloads = {
        "high": catalog_payload({"b": catalog_entry_dict("b", version="9.0.0")}),
        "low": catalog_payload({"b": catalog_entry_dict("b", version="1.0.0")}),
    }
    resolved = _stack(sources, payloads).resolve("b")
    assert resolved.source.id == "high"
    assert resolved.entry.version == "9.0.0"
    assert resolved.install_allowed is False


def test_explicit_catalog_shadows_builtin_community_at_default_priority():
    sources = [
        _source("community", 20, "discovery-only"),
        _source("explicit", 10, "install-allowed"),
    ]
    payloads = {
        "community": catalog_payload(
            {
                "shared": catalog_entry_dict("shared", version="1.0.0"),
            }
        ),
        "explicit": catalog_payload(
            {
                "shared": catalog_entry_dict("shared", version="2.0.0"),
            }
        ),
    }

    resolved = _stack(sources, payloads).resolve("shared")

    assert resolved.source.id == "explicit"
    assert resolved.entry.version == "2.0.0"
    assert resolved.install_allowed is True


def test_resolve_unknown_bundle_errors():
    stack = _stack(
        [_source("only", 1, "install-allowed")],
        {"only": catalog_payload({})},
    )
    with pytest.raises(BundlerError, match="not found"):
        stack.resolve("missing")


def test_search_dedupes_by_precedence_and_filters():
    sources = [_source("a", 1, "install-allowed"), _source("b", 2, "install-allowed")]
    payloads = {
        "a": catalog_payload(
            {
                "alpha": catalog_entry_dict("alpha", role="developer"),
            }
        ),
        "b": catalog_payload(
            {
                "alpha": catalog_entry_dict("alpha", version="0.0.1"),
                "beta": catalog_entry_dict("beta", role="qa"),
            }
        ),
    }
    stack = _stack(sources, payloads)

    all_results = stack.search()
    ids = [r.entry.id for r in all_results]
    assert ids == ["alpha", "beta"]
    # alpha resolved from the higher-precedence source 'a'.
    alpha = next(r for r in all_results if r.entry.id == "alpha")
    assert alpha.source.id == "a"

    qa_only = stack.search("qa")
    assert [r.entry.id for r in qa_only] == ["beta"]


def test_search_does_not_surface_a_shadowed_lower_precedence_entry():
    """Search must resolve each id at its highest-precedence source, then
    filter — never fall through to a shadowed lower-precedence entry the query
    happens to match.

    If the query matched only the lower-precedence copy of an id, search used
    to return that copy, even though `resolve()`/install always use the
    higher-precedence one. That advertised a bundle (name/version/source) the
    user could never actually get.
    """
    sources = [
        _source("high", 1, "install-allowed"),
        _source("low", 2, "install-allowed"),
    ]
    payloads = {
        # Highest-precedence entry for 'shared' does NOT match "widget".
        "high": catalog_payload(
            {
                "shared": catalog_entry_dict(
                    "shared",
                    name="Alpha Tool",
                    role="developer",
                    description="nothing relevant",
                    version="2.0.0",
                ),
            }
        ),
        # Lower-precedence entry for the same id DOES match "widget".
        "low": catalog_payload(
            {
                "shared": catalog_entry_dict(
                    "shared",
                    name="Searchable Widget",
                    version="1.0.0",
                ),
            }
        ),
    }
    stack = _stack(sources, payloads)

    # resolve() uses the high-precedence entry.
    assert stack.resolve("shared").source.id == "high"

    # A query that only the shadowed low-precedence entry matches returns
    # nothing — search agrees with resolve().
    assert stack.search("widget") == []

    # And a query the high-precedence entry matches returns it (from 'high').
    alpha = stack.search("alpha tool")
    assert [r.entry.id for r in alpha] == ["shared"]
    assert alpha[0].source.id == "high"


def test_unreachable_source_raises_named_error():
    def fetcher(src):
        raise RuntimeError("boom")

    stack = CatalogStack([_source("bad", 1, "install-allowed")], fetcher)
    with pytest.raises(BundlerError, match="bad"):
        stack.resolve("anything")


def _versioned_entry():
    return catalog_entry_dict(
        "b",
        version="2.0.0",
        download_url="https://example.com/current.zip",
        sha256="a" * 64,
        releases={
            "1.0.0": {
                "download_url": "https://example.com/old.zip",
                "sha256": "b" * 64,
                "requires": {"speckit_version": ">=0.2.0"},
                "provides": {"extensions": 2},
                "verified": True,
            },
            "1.5.0": {
                "download_url": "https://example.com/middle.zip",
                "sha256": "c" * 64,
            },
        },
    )


def test_legacy_and_versioned_entries_keep_current_fields_and_select_exact():
    legacy = catalog_entry_dict("legacy", version="1.0.0")
    entries = load_catalog_payload(
        catalog_payload({"b": _versioned_entry(), "legacy": legacy})
    )
    assert entries["legacy"].available_versions == ["1.0.0"]
    assert entries["legacy"].select_version("1.0.0") is entries["legacy"]
    current = entries["b"]
    assert current.version == "2.0.0"
    assert current.download_url == "https://example.com/current.zip"
    assert current.available_versions == ["2.0.0", "1.5.0", "1.0.0"]
    assert current.select_version("2").version == "2.0.0"
    historical = current.select_version("1.0")
    assert historical.version == "1.0.0"
    assert historical.download_url == "https://example.com/old.zip"
    assert historical.sha256 == "b" * 64
    assert historical.requires_speckit_version == ">=0.2.0"
    assert historical.provides == {"extensions": 2}
    assert historical.verified is True
    assert current.select_version("1.5.0").requires_speckit_version == ""
    assert current.select_version("1.5.0").provides == {}
    with pytest.raises(BundlerError, match="no release '0.9.0'"):
        entries["legacy"].select_version("0.9.0")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("releases", [], "releases.*mapping"),
        (
            "releases",
            {"bad": {"download_url": "https://example.com/a", "sha256": "a" * 64}},
            "Invalid version",
        ),
        (
            "releases",
            {"2.0": {"download_url": "https://example.com/a", "sha256": "a" * 64}},
            "repeats release",
        ),
        (
            "releases",
            {
                "1.0.0": {"download_url": "https://example.com/a", "sha256": "a" * 64},
                "1.0": {"download_url": "https://example.com/b", "sha256": "b" * 64},
            },
            "repeats release",
        ),
        ("releases", {"1.0.0": []}, "must be a mapping"),
        ("releases", {"1.0.0": {"sha256": "a" * 64}}, "needs a download_url"),
        (
            "releases",
            {"1.0.0": {"download_url": "file:///bundle.zip", "sha256": "a" * 64}},
            "non-HTTPS",
        ),
        ("releases", {"1.0.0": {"download_url": "https://example.com/a"}}, "SHA-256"),
        (
            "releases",
            {"1.0.0": {"download_url": "https://example.com/a", "sha256": "bad"}},
            "SHA-256",
        ),
        (
            "releases",
            {
                "1.0.0": {
                    "download_url": "https://example.com/a",
                    "sha256": "a" * 64,
                    "requires": [],
                }
            },
            "invalid requires",
        ),
        (
            "releases",
            {
                "1.0.0": {
                    "download_url": "https://example.com/a",
                    "sha256": "a" * 64,
                    "requires": {"speckit_version": "nope"},
                }
            },
            "Invalid version constraint",
        ),
        (
            "releases",
            {
                "1.0.0": {
                    "download_url": "https://example.com/a",
                    "sha256": "a" * 64,
                    "requires": {"speckit_version": None},
                }
            },
            "invalid requires.speckit_version",
        ),
        (
            "releases",
            {
                "1.0.0": {
                    "download_url": "https://example.com/a",
                    "sha256": "a" * 64,
                    "provides": [],
                }
            },
            "'provides' must be a mapping",
        ),
        (
            "releases",
            {
                "1.0.0": {
                    "download_url": "https://example.com/a",
                    "sha256": "a" * 64,
                    "id": "other",
                }
            },
            "reserved fields",
        ),
        ("version", "", "no current version"),
    ],
)
def test_rejects_malformed_historical_release(field, value, message):
    entry = _versioned_entry()
    entry[field] = value
    with pytest.raises(BundlerError, match=message):
        load_catalog_payload(catalog_payload({"b": entry}))


@pytest.mark.parametrize("policy", ["install-allowed", "discovery-only"])
def test_exact_release_stays_in_winning_source(policy):
    sources = [_source("high", 0, policy), _source("low", 1, "install-allowed")]
    payloads = {
        "high": catalog_payload({"b": _versioned_entry()}),
        "low": catalog_payload({"b": catalog_entry_dict("b", version="0.9.0")}),
    }
    stack = _stack(sources, payloads)
    selected = stack.resolve("b", "1.0.0")
    assert selected.source.id == "high"
    assert selected.entry.version == "1.0.0"
    assert selected.entry.source_policy is InstallPolicy(policy)
    assert selected.install_allowed is (policy == "install-allowed")
    with pytest.raises(BundlerError, match="no release '0.9.0'"):
        stack.resolve("b", "0.9.0")
    assert stack.search()[0].entry.version == "2.0.0"
