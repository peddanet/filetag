"""Tests of the provider profiles."""
import datetime

import pytest

from filetag_providers import Profile, ProfileRegistry

CHECKED = datetime.date(2026, 11, 14)


def make_profile(**changes: object) -> Profile:
    """Build a valid profile with optional changes.

    Args:
        **changes: Fields to override.

    Returns:
        The profile.
    """
    values = {"id": "x", "name": "X", "kind": "cloud", "api": "openai",
              "endpoint": "https://x.invalid", "video_input": False,
              "adult_content": "risk", "policy_url": "https://x.invalid/policy",
              "policy_checked": CHECKED, "data_use": "none"}
    values.update(changes)
    return Profile(**values)


def test_builtin_profiles_load_and_are_consistent():
    """All shipped profiles load; local ones never send data away."""
    registry = ProfileRegistry.builtin()
    assert {"ollama", "vllm", "gemini", "mistral", "anthropic"} <= set(registry.profiles)
    for profile in registry.profiles.values():
        assert profile.policy_url.startswith(("https://", "http://"))
        if profile.kind == "local":
            assert profile.endpoint.startswith("http://127.0.0.1")
    assert registry.get("anthropic").adult_content == "not_permitted"


@pytest.mark.parametrize("changes", [{"kind": "remote"}, {"api": "soap"},
                                     {"adult_content": "maybe"}])
def test_profile_rejects_unknown_values(changes: dict[str, str]) -> None:
    """Enumerated fields accept only their values.

    Args:
        changes: Field values outside the enumeration.
    """
    with pytest.raises(ValueError):
        make_profile(**changes)


def test_staleness_and_lookup():
    """Old policy facts are reported; unknown ids and duplicates are refused."""
    old = make_profile(id="old", policy_checked=CHECKED - datetime.timedelta(days=91))
    registry = ProfileRegistry([make_profile(), old])
    assert [p.id for p in registry.stale(CHECKED)] == ["old"]
    with pytest.raises(KeyError, match="unknown provider"):
        registry.get("nope")
    with pytest.raises(ValueError, match="duplicate"):
        ProfileRegistry([make_profile(), make_profile()])
