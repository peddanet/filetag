"""SQLite database of the controller."""
from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Any

from filetag_core.entry import ScanEntry

SCHEMA_VERSION = 1

# Version 1: files, where they lie, runs, tags and the full-text index.
# Tables for analysis results (shots, frames, captions, transcripts,
# stories) follow with the analysing worker as schema version 2.
SCHEMA = """
CREATE TABLE runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,
    host           TEXT NOT NULL,
    root           TEXT,
    backend        TEXT,
    model          TEXT,
    prompt_version TEXT,
    started        TEXT NOT NULL,
    finished       TEXT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'done', 'aborted'))
);
CREATE TABLE files (
    id          TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    mime        TEXT,
    first_path  TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
CREATE TABLE locations (
    path           TEXT PRIMARY KEY,
    file_id        TEXT NOT NULL REFERENCES files(id),
    device         INTEGER NOT NULL,
    inode          INTEGER NOT NULL,
    size           INTEGER NOT NULL,
    mtime_ns       INTEGER NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    last_run       INTEGER NOT NULL REFERENCES runs(id),
    missing_since  TEXT
);
CREATE INDEX locations_file ON locations(file_id);
CREATE TABLE tags (
    file_id  TEXT NOT NULL REFERENCES files(id),
    tag      TEXT NOT NULL,
    source   TEXT NOT NULL CHECK (source IN ('controlled', 'free')),
    run_id   INTEGER REFERENCES runs(id),
    PRIMARY KEY (file_id, tag)
);
CREATE VIRTUAL TABLE fts USING fts5(file_id UNINDEXED, title, story, transcript, tags);
"""


class Database:
    """Stores what filetag knows about files; never touches the files.

    Rows are never deleted by a scan: a path that disappeared gets a
    ``missing_since`` time, a file whose content changed gets a new ``files``
    row while the old one stays as history.

    Attributes:
        path: Database file, or ``:memory:``.
        conn: Open connection.
    """

    def __init__(self, path: str):
        """Open the database and create or check its schema.

        Args:
            path: Database file, or ``:memory:`` for tests.

        Raises:
            RuntimeError: The file has a newer schema than this version knows.
        """
        self.path = path
        self.conn = sqlite3.connect(path)
        try:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.migrate()
        except BaseException:
            self.conn.close()
            raise

    def __enter__(self) -> "Database":
        """Use the database as a context manager.

        Returns:
            The database itself.
        """
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        """Commit on success, roll back on error, then close.

        Args:
            exc_type: Type of a raised exception, or None.
            exc: The exception, or None.
            tb: Its traceback, or None.
        """
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def version(self) -> int:
        """Read the schema version.

        Returns:
            ``PRAGMA user_version``; 0 for an empty database.
        """
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        """Create the schema in an empty database.

        Raises:
            RuntimeError: The database has a newer schema.
        """
        current = self.version()
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {current} is newer than {SCHEMA_VERSION}; "
                               "update filetag")
        if current == 0:
            self.conn.executescript(SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION};")

    def commit(self) -> None:
        """Commit the open transaction."""
        self.conn.commit()

    def start_run(self, kind: str, host: str, root: str | None, now: str) -> int:
        """Record the start of a run.

        Args:
            kind: ``scan`` or an analysis kind.
            host: Host name of the controller.
            root: Scanned folder, if any.
            now: Time stamp (ISO 8601, UTC).

        Returns:
            Id of the run.
        """
        cur = self.conn.execute(
            "INSERT INTO runs (kind, host, root, started, status) VALUES (?, ?, ?, ?, 'running')",
            (kind, host, root, now))
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, status: str, now: str) -> None:
        """Record the end of a run and commit.

        Args:
            run_id: Id from ``start_run``.
            status: ``done`` or ``aborted``.
            now: Time stamp.
        """
        self.conn.execute("UPDATE runs SET status = ?, finished = ? WHERE id = ?",
                          (status, now, run_id))
        self.conn.commit()

    def location(self, path: str) -> tuple[ScanEntry, str] | None:
        """Look up what is known about a path.

        Args:
            path: Absolute path.

        Returns:
            The stored entry and its file id, or None.
        """
        row = self.conn.execute(
            "SELECT device, inode, size, mtime_ns, file_id FROM locations WHERE path = ?",
            (path,)).fetchone()
        if row is None:
            return None
        return ScanEntry(path, row[0], row[1], row[2], row[3]), str(row[4])

    def add_file(self, file_id: str, size: int, kind: str, mime: str | None, path: str,
                 now: str) -> bool:
        """Register a file content, or update its last-seen time.

        Args:
            file_id: Fingerprint.
            size: Size in bytes.
            kind: One of ``filekind.KINDS``.
            mime: MIME type or None.
            path: Path where it was seen first.
            now: Time stamp.

        Returns:
            True when the content was new.
        """
        cur = self.conn.execute(
            "INSERT INTO files (id, size, kind, mime, first_path, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            (file_id, size, kind, mime, path, now, now))
        if cur.rowcount:
            return True
        self.conn.execute("UPDATE files SET last_seen = ? WHERE id = ?", (now, file_id))
        return False

    def put_location(self, entry: ScanEntry, file_id: str, run_id: int, now: str) -> None:
        """Insert or replace what is known about a path.

        Args:
            entry: Current state of the path.
            file_id: Fingerprint of its content.
            run_id: Current run.
            now: Time stamp.
        """
        self.conn.execute(
            "INSERT INTO locations (path, file_id, device, inode, size, mtime_ns, first_seen, "
            "last_seen, last_run) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (path) DO UPDATE "
            "SET file_id = excluded.file_id, device = excluded.device, inode = excluded.inode, "
            "size = excluded.size, mtime_ns = excluded.mtime_ns, last_seen = excluded.last_seen, "
            "last_run = excluded.last_run, missing_since = NULL",
            (entry.path, file_id, entry.device, entry.inode, entry.size, entry.mtime_ns,
             now, now, run_id))

    def seen(self, path: str, file_id: str, run_id: int, now: str) -> None:
        """Mark an unchanged path and its content as seen in this run.

        Args:
            path: Absolute path.
            file_id: Its stored fingerprint.
            run_id: Current run.
            now: Time stamp.
        """
        self.conn.execute("UPDATE locations SET last_seen = ?, last_run = ?, "
                          "missing_since = NULL WHERE path = ?", (now, run_id, path))
        self.conn.execute("UPDATE files SET last_seen = ? WHERE id = ?", (now, file_id))

    def mark_missing(self, root: str, run_id: int, now: str) -> int:
        """Flag paths below ``root`` that the run did not see.

        Args:
            root: Absolute folder of a complete scan.
            run_id: The scan run.
            now: Time stamp.

        Returns:
            Number of paths newly flagged as missing.
        """
        prefix = root.rstrip("/") + "/"
        cur = self.conn.execute(
            "UPDATE locations SET missing_since = ? WHERE substr(path, 1, ?) = ? "
            "AND last_run <> ? AND missing_since IS NULL", (now, len(prefix), prefix, run_id))
        return cur.rowcount

    def status(self) -> dict[str, Any]:
        """Summarise the content of the database.

        Returns:
            Schema version, files per kind, paths present and missing, and
            the last run as ``(id, kind, status, started, finished)``.
        """
        kinds = dict(self.conn.execute(
            "SELECT kind, count(*) FROM files GROUP BY kind ORDER BY kind").fetchall())
        present, missing = self.conn.execute(
            "SELECT count(*) - count(missing_since), count(missing_since) "
            "FROM locations").fetchone()
        last = self.conn.execute("SELECT id, kind, status, started, finished FROM runs "
                                 "ORDER BY id DESC LIMIT 1").fetchone()
        return {"schema": self.version(), "files": kinds, "paths": present,
                "missing": missing, "last_run": last}
