"""Counters of one scan."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanSummary:
    """What a scan found.

    Attributes:
        run_id: Id of the scan run.
        root: Scanned folder.
        seen: Regular files that passed the filters.
        new_files: Contents not known before.
        new_paths: Paths not known before.
        changed: Known paths whose inode state changed (re-hashed).
        unchanged: Known paths with unchanged inode state (not re-hashed).
        missing: Known paths below the root that were not found any more.
        missing_checked: True when missing paths were looked for (complete
            scan without unreadable folders).
        errors: ``(path, message)`` of unreadable folders and files.
        aborted: True when the scan was interrupted.
    """

    run_id: int
    root: str
    seen: int = 0
    new_files: int = 0
    new_paths: int = 0
    changed: int = 0
    unchanged: int = 0
    missing: int = 0
    missing_checked: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)
    aborted: bool = False

    def line(self) -> str:
        """Render the summary as one line.

        Returns:
            Human-readable summary.
        """
        state = "aborted" if self.aborted else "done"
        missing = f"{self.missing} missing" if self.missing_checked else "missing not checked"
        return (f"scan {state}: {self.seen} files, {self.new_files} new contents, "
                f"{self.new_paths} new paths, {self.changed} changed, {self.unchanged} "
                f"unchanged, {missing}, {len(self.errors)} errors")
