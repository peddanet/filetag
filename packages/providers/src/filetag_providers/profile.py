"""Description of one model backend."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

KINDS = ("local", "cloud")
APIS = ("openai", "ollama", "gemini", "anthropic")
VERDICTS = ("permitted", "risk", "not_permitted")


@dataclass(frozen=True)
class Profile:
    """Facts about one backend.

    Attributes:
        id: Short identifier used on the command line (``--cloud mistral``).
        name: Display name.
        kind: ``local`` (own hardware) or ``cloud``.
        api: Request format the adapter speaks.
        endpoint: Base URL of the API.
        video_input: Whether whole video files are accepted.
        adult_content: Verdict of the content policy for adult content.
        policy_url: Page the verdict is based on.
        policy_checked: Date the policy page was last read.
        data_use: One-line summary of training and retention.
    """

    id: str
    name: str
    kind: str
    api: str
    endpoint: str
    video_input: bool
    adult_content: str
    policy_url: str
    policy_checked: datetime.date
    data_use: str

    def __post_init__(self) -> None:
        """Validate the enumerated fields.

        Raises:
            ValueError: A field has a value outside its enumeration.
        """
        for name, value, allowed in (("kind", self.kind, KINDS), ("api", self.api, APIS),
                                     ("adult_content", self.adult_content, VERDICTS)):
            if value not in allowed:
                raise ValueError(f"profile {self.id}: {name} '{value}' not in {allowed}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        """Build a profile from decoded JSON.

        Args:
            data: Decoded profile file.

        Returns:
            The profile.
        """
        values = dict(data)
        values["policy_checked"] = datetime.date.fromisoformat(str(data["policy_checked"]))
        return cls(**values)

    def is_stale(self, today: datetime.date, max_age_days: int) -> bool:
        """Tell whether the policy facts need to be checked again.

        Args:
            today: Current date.
            max_age_days: Accepted age of the facts.

        Returns:
            True if the facts are older than ``max_age_days``.
        """
        return (today - self.policy_checked).days > max_age_days
