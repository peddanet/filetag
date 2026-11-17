"""File names of the flat view."""
from __future__ import annotations

import re

MAX_BYTES = 255
_UNSAFE = re.compile(r"[/\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_HEX = re.compile(r"[0-9a-f]{4,}")


class FlatNamer:
    """Builds ``<title> [<language tag>] [<id>]<ext>`` names.

    The short id (first four hex digits of the file id) keeps names unique
    when two files get the same title. Names never exceed ``MAX_BYTES``
    bytes in UTF-8; the title is shortened, never the tag, id or extension.

    Attributes:
        max_bytes: Upper limit of a file name in bytes.
    """

    def __init__(self, max_bytes: int = MAX_BYTES):
        """Set the length limit.

        Args:
            max_bytes: Upper limit of a file name in bytes (file system limit).
        """
        self.max_bytes = max_bytes

    @staticmethod
    def clean(title: str) -> str:
        """Make a title safe for a file name.

        Args:
            title: Title as produced by the model.

        Returns:
            Title without slashes and control characters, single spaces, no
            leading dots or dashes, no trailing dots; ``untitled`` if empty.
        """
        text = _SPACES.sub(" ", _UNSAFE.sub(" ", title)).strip()
        text = text.lstrip(".- ").rstrip(". ")
        return text or "untitled"

    def build(self, title: str, tag: str, file_id: str, ext: str) -> str:
        """Build the flat-view name of one file.

        Args:
            title: Descriptive title.
            tag: Language tag from ``LanguageTagger.title_tag`` (may be empty).
            file_id: Hex id of the file; its first four digits are used.
            ext: Extension including the dot, e.g. ``.mp4``; may be empty.

        Returns:
            The file name.

        Raises:
            ValueError: ``file_id`` is not hex, or the fixed parts alone
                exceed the limit.
        """
        if not _HEX.fullmatch(file_id):
            raise ValueError(f"file id must be at least 4 lower-case hex digits: {file_id!r}")
        suffix = (f" {tag}" if tag else "") + f" [{file_id[:4]}]" + ext
        budget = self.max_bytes - len(suffix.encode("utf-8"))
        if budget < 1:
            raise ValueError("language tag, id and extension exceed the name limit")
        head = self.clean(title).encode("utf-8")[:budget].decode("utf-8", errors="ignore")
        return self.clean(head) + suffix
