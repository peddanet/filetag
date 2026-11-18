"""Bring the database in line with a folder tree."""
from __future__ import annotations

import os
import socket
from collections.abc import Callable
from datetime import datetime, timezone

from filetag_core.database import Database
from filetag_core.entry import ScanEntry
from filetag_core.filekind import KindClassifier
from filetag_core.fingerprint import Fingerprinter
from filetag_core.scanner import Scanner
from filetag_core.summary import ScanSummary

BATCH = 200


def utc_now() -> str:
    """Current time for the database.

    Returns:
        ISO 8601 time stamp in UTC with seconds.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Indexer:
    """Registers every file below a root with its provenance.

    A path whose device, inode, size and modification time are unchanged
    since the last scan is not read again, so a repeated scan only costs
    one ``lstat`` per file. Every ``BATCH`` files the work is committed, so
    an interrupted scan keeps what it did and the next scan continues
    cheaply. Paths are flagged missing only after a complete scan without
    unreadable folders; an unreadable file keeps its last known state.

    Attributes:
        db: Database.
        scanner: Folder walker with its filters.
        fingerprinter: Content hash.
        classifier: Kind and MIME type.
        clock: Function returning the current time stamp.
        host: Host name recorded with the run.
        progress: Called with the number of files seen every ``BATCH`` files.
    """

    def __init__(self, db: Database, scanner: Scanner,
                 fingerprinter: Fingerprinter | None = None,
                 classifier: KindClassifier | None = None,
                 clock: Callable[[], str] = utc_now, host: str | None = None,
                 progress: Callable[[int], None] | None = None):
        """Inject the collaborators.

        Args:
            db: Database.
            scanner: Folder walker.
            fingerprinter: Content hash; default ``Fingerprinter()``.
            classifier: Kind lookup; default ``KindClassifier()``.
            clock: Time stamp source.
            host: Host name; default ``socket.gethostname()``.
            progress: Optional progress callback.
        """
        self.db = db
        self.scanner = scanner
        self.fingerprinter = fingerprinter or Fingerprinter()
        self.classifier = classifier or KindClassifier()
        self.clock = clock
        self.host = host or socket.gethostname()
        self.progress = progress

    def _register(self, entry: ScanEntry, summary: ScanSummary) -> None:
        """Bring one path up to date.

        Args:
            entry: Current state of the path.
            summary: Counters to update.
        """
        now = self.clock()
        known = self.db.location(entry.path)
        if known is not None and known[0].same_inode_state(entry):
            self.db.seen(entry.path, known[1], summary.run_id, now)
            summary.unchanged += 1
            return
        try:
            file_id = self.fingerprinter.digest(entry.path, entry.size)
        except OSError as exc:
            summary.errors.append((entry.path, exc.strerror or str(exc)))
            if known is not None:
                self.db.seen(entry.path, known[1], summary.run_id, now)
            return
        kind, mime = self.classifier.classify(entry.path)
        if self.db.add_file(file_id, entry.size, kind, mime, entry.path, now):
            summary.new_files += 1
        self.db.put_location(entry, file_id, summary.run_id, now)
        if known is None:
            summary.new_paths += 1
        else:
            summary.changed += 1

    def scan(self, root: str) -> ScanSummary:
        """Scan a folder tree.

        Args:
            root: Folder to scan.

        Returns:
            Counters of the scan. On Ctrl+C the run is recorded as
            ``aborted``, the work done so far is kept and ``aborted`` is set.

        Raises:
            NotADirectoryError: ``root`` is not a folder.
        """
        root = os.path.realpath(root)
        if not os.path.isdir(root):
            raise NotADirectoryError(f"not a folder: {root}")
        summary = ScanSummary(self.db.start_run("scan", self.host, root, self.clock()), root)
        try:
            for entry in self.scanner.walk(root):
                self._register(entry, summary)
                summary.seen += 1
                if summary.seen % BATCH == 0:
                    self.db.commit()
                    if self.progress:
                        self.progress(summary.seen)
        except KeyboardInterrupt:
            summary.aborted = True
        folder_errors = list(self.scanner.errors)
        summary.errors = folder_errors + summary.errors
        if not summary.aborted and not folder_errors:
            summary.missing = self.db.mark_missing(root, summary.run_id, self.clock())
            summary.missing_checked = True
        self.db.finish_run(summary.run_id, "aborted" if summary.aborted else "done",
                           self.clock())
        return summary
