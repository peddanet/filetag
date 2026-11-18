"""Walk a folder tree and report its regular files."""
from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Iterator

from filetag_core.entry import ScanEntry

SKIP_DIRS = frozenset({"geloescht"})


class Scanner:
    """Finds regular files below a root, optionally filtered by extension.

    Symbolic links are neither followed nor reported; devices, sockets and
    pipes are ignored. Folders named like an entry of ``skip_dirs`` (by
    default ``geloescht``, where filetag moves obsolete items) are not
    entered. Unreadable folders and files are collected in ``errors``; the
    walk continues.

    Attributes:
        include: Extensions to report (lower case, with dot); None for all.
        exclude: Extensions never to report.
        skip_dirs: Folder names that are not entered.
        skip_paths: Absolute paths never to report (the database itself).
        errors: ``(path, message)`` pairs of the last walk.
    """

    def __init__(self, include: Iterable[str] | None = None, exclude: Iterable[str] = (),
                 skip_dirs: Iterable[str] = SKIP_DIRS, skip_paths: Iterable[str] = ()):
        """Set the filters.

        Args:
            include: Extensions to report, e.g. ``[".mp4", "mkv"]``; None for all.
            exclude: Extensions never to report.
            skip_dirs: Folder names that are not entered.
            skip_paths: Absolute paths never to report.
        """
        self.include = None if include is None else {self.norm_ext(e) for e in include}
        self.exclude = {self.norm_ext(e) for e in exclude}
        self.skip_dirs = frozenset(skip_dirs)
        self.skip_paths = frozenset(os.path.abspath(p) for p in skip_paths)
        self.errors: list[tuple[str, str]] = []

    @staticmethod
    def norm_ext(ext: str) -> str:
        """Normalise an extension.

        Args:
            ext: Extension with or without dot, any case.

        Returns:
            Lower-case extension with a leading dot.
        """
        ext = ext.strip().lower()
        return ext if ext.startswith(".") else "." + ext

    def wanted(self, name: str) -> bool:
        """Apply the extension filters to a file name.

        Args:
            name: File name.

        Returns:
            True when the file is to be reported.
        """
        ext = os.path.splitext(name)[1].lower()
        if ext in self.exclude:
            return False
        return self.include is None or ext in self.include

    def _error(self, exc: OSError) -> None:
        """Record an error of ``os.walk``.

        Args:
            exc: The error; its ``filename`` names the folder.
        """
        self.errors.append((str(exc.filename), exc.strerror or str(exc)))

    def walk(self, root: str) -> Iterator[ScanEntry]:
        """Walk the tree below ``root`` in sorted order.

        Args:
            root: Folder to scan.

        Yields:
            One entry per regular file that passes the filters.
        """
        self.errors = []
        for folder, dirs, files in os.walk(os.path.abspath(root), onerror=self._error):
            dirs[:] = sorted(d for d in dirs if d not in self.skip_dirs)
            for name in sorted(files):
                path = os.path.join(folder, name)
                if path in self.skip_paths or not self.wanted(name):
                    continue
                try:
                    info = os.lstat(path)
                except OSError as exc:
                    self.errors.append((path, exc.strerror or str(exc)))
                    continue
                if stat.S_ISREG(info.st_mode):
                    yield ScanEntry(path, info.st_dev, info.st_ino, info.st_size,
                                    info.st_mtime_ns)
