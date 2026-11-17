"""All profiles shipped with the package."""
from __future__ import annotations

import datetime
import json
from importlib import resources

from filetag_providers.profile import Profile


class ProfileRegistry:
    """Loads and looks up provider profiles.

    Attributes:
        profiles: Profiles by id, sorted by id.
    """

    MAX_AGE_DAYS = 90

    def __init__(self, profiles: list[Profile]):
        """Index the given profiles.

        Args:
            profiles: Profiles to manage.

        Raises:
            ValueError: Two profiles share an id.
        """
        self.profiles: dict[str, Profile] = {}
        for profile in sorted(profiles, key=lambda p: p.id):
            if profile.id in self.profiles:
                raise ValueError(f"duplicate profile id: {profile.id}")
            self.profiles[profile.id] = profile

    @classmethod
    def builtin(cls) -> ProfileRegistry:
        """Load the profiles shipped in ``filetag_providers/profiles``.

        Returns:
            The registry.
        """
        folder = resources.files("filetag_providers").joinpath("profiles")
        loaded = [Profile.from_dict(json.loads(entry.read_text(encoding="utf-8")))
                  for entry in folder.iterdir() if entry.name.endswith(".json")]
        return cls(loaded)

    def get(self, profile_id: str) -> Profile:
        """Return one profile.

        Args:
            profile_id: Id of the profile.

        Returns:
            The profile.

        Raises:
            KeyError: No profile with this id.
        """
        try:
            return self.profiles[profile_id]
        except KeyError:
            raise KeyError(f"unknown provider: {profile_id} "
                           f"(known: {', '.join(self.profiles)})") from None

    def stale(self, today: datetime.date) -> list[Profile]:
        """Return the profiles whose policy facts are too old.

        Args:
            today: Current date.

        Returns:
            Stale profiles, sorted by id.
        """
        return [p for p in self.profiles.values() if p.is_stale(today, self.MAX_AGE_DAYS)]
