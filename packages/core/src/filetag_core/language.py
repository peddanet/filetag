"""Language rules for titles and companion texts."""
from __future__ import annotations

import re

NAMES = {
    "ar": "Arabic", "de": "German", "en": "English", "es": "Spanish", "fr": "French",
    "hi": "Hindi", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "kn": "Kannada",
    "ko": "Korean", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "ru": "Russian",
    "ta": "Tamil", "te": "Telugu", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "vi": "Vietnamese", "zh": "Chinese",
}
_CODE = re.compile(r"[a-z]{2}")


class LanguageTagger:
    """Applies the language rules of the owner.

    * English or no speech: English text, no tag in the title.
    * German: German and English text, tag ``[de-German]``.
    * Any other language: English text, tag ``[<code>-<Name>]``; a code
      without a known name gives ``[<code>]``.

    Attributes:
        names: English names by ISO 639-1 code.
    """

    def __init__(self, names: dict[str, str] | None = None):
        """Set the name table.

        Args:
            names: English names by ISO 639-1 code; default ``NAMES``.
        """
        self.names = dict(NAMES if names is None else names)

    @staticmethod
    def normalise(code: str | None) -> str | None:
        """Normalise a language code as delivered by speech recognition.

        Args:
            code: Code such as ``"PT"``, ``"pt"`` or ``"pt-BR"``; None or
                empty for no speech.

        Returns:
            Lower-case two-letter code, or None.

        Raises:
            ValueError: The code does not start with two letters.
        """
        if not code:
            return None
        base = code.strip().lower().replace("_", "-").split("-", 1)[0]
        if not _CODE.fullmatch(base):
            raise ValueError(f"not an ISO 639-1 code: {code!r}")
        return base

    def title_tag(self, code: str | None) -> str:
        """Return the tag that the title carries.

        Args:
            code: Detected language code, or None for no speech.

        Returns:
            ``""`` for English or no speech, otherwise e.g. ``[pt-Portuguese]``.
        """
        base = self.normalise(code)
        if base in (None, "en"):
            return ""
        name = self.names.get(str(base))
        return f"[{base}-{name}]" if name else f"[{base}]"

    def needs_german(self, code: str | None) -> bool:
        """Tell whether a German description is written besides the English one.

        Args:
            code: Detected language code, or None.

        Returns:
            True for German speech.
        """
        return self.normalise(code) == "de"
