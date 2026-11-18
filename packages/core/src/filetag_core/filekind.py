"""Coarse kind of a file, which decides the analysis module later."""
from __future__ import annotations

import mimetypes

KINDS = ("video", "image", "audio", "document", "other")

# Extensions whose MIME type differs between Python 3.12, 3.13 and 3.14 or
# is missing in the built-in table of the standard library (compared on
# 2026-11-18). They are pinned here to the values of Python 3.14, so the
# database gets the same type on every machine. The system tables
# (/etc/mime.types) are not read for the same reason.
PINNED = {
    ".mkv": "video/matroska", ".m4v": "video/x-m4v", ".avi": "video/vnd.avi",
    ".wmv": "video/x-ms-wmv", ".flv": "video/x-flv", ".ogv": "video/ogg",
    ".ts": "video/mp2t", ".mts": "video/mp2t", ".m2ts": "video/mp2t",
    ".m4a": "audio/mp4", ".flac": "audio/flac", ".wav": "audio/vnd.wave",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".wma": "audio/x-ms-wma",
    ".md": "text/markdown", ".rtf": "text/rtf", ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".7z": "application/x-7z-compressed", ".rar": "application/vnd.rar",
}
DOCUMENT_TYPES = ("application/pdf", "application/epub+zip", "application/msword",
                  "application/vnd.oasis.opendocument.text",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class KindClassifier:
    """Maps a file name to a MIME type and one of ``KINDS``.

    Only the extension is used; the content is not inspected.

    Attributes:
        table: MIME table of the standard library without system files.
    """

    def __init__(self) -> None:
        """Load the built-in MIME table and override it with ``PINNED``."""
        self.table = mimetypes.MimeTypes(filenames=())
        for ext, mime in PINNED.items():
            self.table.add_type(mime, ext)

    def classify(self, name: str) -> tuple[str, str | None]:
        """Classify a file name.

        Args:
            name: File name or path.

        Returns:
            ``(kind, mime)``; ``mime`` is None for an unknown extension.
        """
        mime, _ = self.table.guess_type(name.lower(), strict=False)
        if mime is None:
            return "other", None
        major = mime.split("/", 1)[0]
        if major in ("video", "image", "audio"):
            return major, mime
        if major == "text" or mime in DOCUMENT_TYPES:
            return "document", mime
        return "other", mime
