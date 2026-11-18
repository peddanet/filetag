"""Tests of the scan: data folder, fingerprint, kinds, walker, database, indexer, CLI."""
import hashlib
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from filetag_core import indexer as indexer_module
from filetag_core.cli import Cli
from filetag_core.database import Database
from filetag_core.entry import ScanEntry
from filetag_core.filekind import KindClassifier
from filetag_core.fingerprint import Fingerprinter
from filetag_core.home import Home
from filetag_core.indexer import Indexer, utc_now
from filetag_core.scanner import Scanner
from filetag_core.summary import ScanSummary


def write(path: Path, data: bytes) -> Path:
    """Create a file with its parent folders.

    Args:
        path: File to create.
        data: Content.

    Returns:
        The path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture(name="tree")
def fixture_tree(tmp_path: Path) -> Path:
    """A small archive with several kinds, a link and a moved-away item.

    Args:
        tmp_path: pytest fixture with an empty folder.

    Returns:
        Root of the archive.
    """
    root = tmp_path / "archive"
    write(root / "a" / "clip.MP4", b"video-1")
    write(root / "a" / "photo.jpg", b"image-1")
    write(root / "b" / "talk.flac", b"audio-1")
    write(root / "b" / "notes.md", b"text-1")
    write(root / "b" / "blob.xyz", b"other-1")
    write(root / "geloescht" / "old.mp4", b"video-old")
    os.symlink(root / "a" / "clip.MP4", root / "link.mp4")
    os.link(root / "a" / "clip.MP4", root / "b" / "hardlink.mp4")
    return root


def test_home_default_env_and_ensure(tmp_path: Path) -> None:
    """The data folder follows $FILETAG_HOME and is created private.

    Args:
        tmp_path: pytest fixture with an empty folder.
    """
    assert Home({}).root == Path("~/.local/share/filetag").expanduser()
    home = Home({"FILETAG_HOME": str(tmp_path / "h")})
    assert home.database == tmp_path / "h" / "filetag.db"
    assert home.ensure().is_dir()
    assert (tmp_path / "h").stat().st_mode & 0o777 == 0o700
    assert Home().root.is_absolute()


def test_fingerprint_small_large_and_errors(tmp_path: Path) -> None:
    """Small files are hashed whole, large ones at both ends only.

    Args:
        tmp_path: pytest fixture with an empty folder.
    """
    small = write(tmp_path / "s", b"abcdef")
    expected = hashlib.sha256((6).to_bytes(8, "big") + b"abcdef").hexdigest()
    assert Fingerprinter(chunk=4, block=2).digest(str(small), 6) == expected
    big = write(tmp_path / "b", b"HEAD" + b"middle" + b"TAIL")
    expected = hashlib.sha256((14).to_bytes(8, "big") + b"HEAD" + b"TAIL").hexdigest()
    assert Fingerprinter(chunk=4, block=3).digest(str(big), 14) == expected
    other_middle = write(tmp_path / "c", b"HEAD" + b"MIDDLE" + b"TAIL")
    assert Fingerprinter(chunk=4).digest(str(other_middle), 14) == expected
    with pytest.raises(OSError):
        Fingerprinter().digest(str(small), 99)
    with pytest.raises(ValueError):
        Fingerprinter(chunk=0)


@pytest.mark.parametrize("name, kind, mime", [
    ("x.mp4", "video", "video/mp4"), ("X.MKV", "video", "video/matroska"),
    ("x.avi", "video", "video/vnd.avi"), ("x.wav", "audio", "audio/vnd.wave"),
    ("x.rtf", "document", "text/rtf"),
    ("x.docx", "document",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("x.jpg", "image", "image/jpeg"), ("x.flac", "audio", "audio/flac"),
    ("x.md", "document", "text/markdown"), ("x.pdf", "document", "application/pdf"),
    ("x.zip", "other", "application/zip"), ("x.xyz", "other", None), ("noext", "other", None)])
def test_kind(name: str, kind: str, mime: str | None) -> None:
    """Extensions map to a kind independent of the system MIME tables.

    Args:
        name: File name.
        kind: Expected kind.
        mime: Expected MIME type.
    """
    assert KindClassifier().classify(name) == (kind, mime)


def test_scanner_filters_links_and_skip_dirs(tree: Path) -> None:
    """Only regular files pass; links are not followed; geloescht is not entered.

    Args:
        tree: Test archive.
    """
    names = [os.path.relpath(e.path, tree) for e in Scanner().walk(str(tree))]
    assert names == ["a/clip.MP4", "a/photo.jpg", "b/blob.xyz", "b/hardlink.mp4",
                     "b/notes.md", "b/talk.flac"]
    only = Scanner(include=["MP4", ".jpg"], exclude=["jpg"]).walk(str(tree))
    assert [os.path.basename(e.path) for e in only] == ["clip.MP4", "hardlink.mp4"]
    skip = Scanner(skip_paths=[str(tree / "b" / "notes.md")], skip_dirs=["a", "b"])
    assert [os.path.basename(e.path) for e in skip.walk(str(tree))] == ["old.mp4"]


def test_scanner_records_errors(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unreadable folders and files are recorded, the walk goes on.

    Args:
        tree: Test archive.
        monkeypatch: pytest fixture replacing os.lstat.
    """
    scanner = Scanner()
    assert not list(scanner.walk(str(tree / "nowhere")))
    assert scanner.errors and scanner.errors[0][0].endswith("nowhere")
    real = os.lstat

    def lstat(path: str) -> os.stat_result:
        """Fail for one file.

        Args:
            path: Path to examine.

        Returns:
            Result of the real lstat.

        Raises:
            PermissionError: For notes.md.
        """
        if path.endswith("notes.md"):
            raise PermissionError(13, "Permission denied", path)
        return real(path)

    monkeypatch.setattr(os, "lstat", lstat)
    assert len(list(scanner.walk(str(tree)))) == 5
    assert scanner.errors == [(str(tree / "b" / "notes.md"), "Permission denied")]


def test_entry_inode_state() -> None:
    """Two entries agree when device, inode, size and time agree."""
    one = ScanEntry("/p", 1, 2, 3, 4)
    assert one.same_inode_state(ScanEntry("/q", 1, 2, 3, 4))
    assert not one.same_inode_state(ScanEntry("/p", 1, 2, 3, 5))


def test_database_schema_and_context(tmp_path: Path) -> None:
    """The schema is created once, checked, and the context manager commits or rolls back.

    Args:
        tmp_path: pytest fixture with an empty folder.

    Raises:
        ZeroDivisionError: Never escapes; it provokes the rollback.
    """
    path = str(tmp_path / "t.db")
    with Database(path) as db:
        assert db.version() == 1
        assert db.status() == {"schema": 1, "files": {}, "paths": 0, "missing": 0,
                               "last_run": None}
        db.start_run("scan", "h", None, "t0")
    with pytest.raises(ZeroDivisionError):
        with Database(path) as db:
            db.conn.execute("INSERT INTO files VALUES ('x', 1, 'other', NULL, '/x', 't', 't')")
            raise ZeroDivisionError
    with Database(path) as db:
        assert not db.status()["files"]
        assert db.status()["last_run"] == (1, "scan", "running", "t0", None)
        db.conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError):
        Database(path)


def test_indexer_first_scan_rescan_change_and_missing(tree: Path, tmp_path: Path) -> None:
    """A rescan reads nothing again, a change re-hashes, a vanished path is flagged.

    Args:
        tree: Test archive.
        tmp_path: pytest fixture with an empty folder.
    """
    ticks = iter(f"t{i:03}" for i in range(1000))
    seen: list[int] = []
    with Database(str(tmp_path / "x.db")) as db:
        indexer = Indexer(db, Scanner(), clock=lambda: next(ticks), host="h",
                          progress=seen.append)
        first = indexer.scan(str(tree))
        assert (first.seen, first.new_files, first.new_paths, first.unchanged) == (6, 5, 6, 0)
        assert first.missing_checked and first.missing == 0 and not first.errors
        assert db.status()["files"] == {"audio": 1, "document": 1, "image": 1, "other": 1,
                                        "video": 1}
        clip = db.location(str(tree / "a" / "clip.MP4"))
        hard = db.location(str(tree / "b" / "hardlink.mp4"))
        assert clip and hard and clip[1] == hard[1] and clip[0].inode == hard[0].inode

        write(tree / "b" / "notes.md", b"text-2, longer")
        os.rename(tree / "a" / "photo.jpg", tree / "geloescht" / "photo.jpg")
        second = indexer.scan(str(tree))
        assert (second.changed, second.unchanged, second.new_files, second.missing) == (
            1, 4, 1, 1)
        assert "1 missing" in second.line() and second.line().startswith("scan done")
        row = db.conn.execute("SELECT missing_since FROM locations WHERE path LIKE "
                              "'%photo.jpg'").fetchone()
        assert row[0] is not None
        assert db.status()["missing"] == 1 and db.status()["paths"] == 5
        assert db.conn.execute("SELECT count(*) FROM files").fetchone()[0] == 6

        os.rename(tree / "geloescht" / "photo.jpg", tree / "a" / "photo.jpg")
        third = indexer.scan(str(tree))
        assert third.missing == 0 and db.status()["missing"] == 0
        assert not seen
        with pytest.raises(NotADirectoryError):
            indexer.scan(str(tree / "a" / "clip.MP4"))


class FailingFingerprinter(Fingerprinter):
    """Raises for every path ending in a given suffix.

    Attributes:
        suffix: Suffix of the paths that fail.
    """

    def __init__(self, suffix: str):
        """Set the failing suffix.

        Args:
            suffix: Suffix of the paths that fail.
        """
        super().__init__()
        self.suffix = suffix

    def digest(self, path: str, size: int) -> str:
        """Fail or hash.

        Args:
            path: File to read.
            size: Its size.

        Returns:
            The real fingerprint.

        Raises:
            PermissionError: For the failing suffix.
        """
        if path.endswith(self.suffix):
            raise PermissionError(13, "Permission denied", path)
        return super().digest(path, size)


class BrokenScanner(Scanner):
    """Reports a folder error, optionally after an interrupt.

    Attributes:
        interrupt: Raise KeyboardInterrupt after the first entry.
    """

    def __init__(self, interrupt: bool):
        """Set the behaviour.

        Args:
            interrupt: Raise KeyboardInterrupt after the first entry.
        """
        super().__init__()
        self.interrupt = interrupt

    def walk(self, root: str) -> Iterator[ScanEntry]:
        """Yield the first entry, then fail.

        Args:
            root: Folder to scan.

        Yields:
            The first entry of the real walk.

        Raises:
            KeyboardInterrupt: When ``interrupt`` is set.
        """
        yield from list(Scanner().walk(root))[:1]
        self.errors = [(root + "/locked", "Permission denied")]
        if self.interrupt:
            raise KeyboardInterrupt


def test_indexer_errors_keep_state_and_skip_missing(tree: Path) -> None:
    """Unreadable files keep their known state; folder errors and Ctrl+C skip the missing check.

    Args:
        tree: Test archive.
    """
    with Database(":memory:") as db:
        Indexer(db, Scanner(), host="h").scan(str(tree))
        write(tree / "b" / "notes.md", b"changed")
        write(tree / "b" / "new.md", b"new")
        result = Indexer(db, Scanner(), fingerprinter=FailingFingerprinter(".md"),
                         host="h").scan(str(tree))
        assert len(result.errors) == 2 and result.missing == 0 and result.missing_checked
        assert db.location(str(tree / "b" / "new.md")) is None

        broken = Indexer(db, BrokenScanner(interrupt=False), host="h").scan(str(tree))
        assert broken.seen == 1 and not broken.missing_checked and not broken.aborted
        assert "missing not checked" in broken.line()
        stopped = Indexer(db, BrokenScanner(interrupt=True), host="h").scan(str(tree))
        assert stopped.aborted and stopped.line().startswith("scan aborted")
        assert db.status()["last_run"][2] == "aborted" and db.status()["missing"] == 0


def test_indexer_progress_every_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Progress is reported and work committed every batch.

    Args:
        tmp_path: pytest fixture with an empty folder.
        monkeypatch: pytest fixture shrinking the batch size.
    """
    for i in range(5):
        write(tmp_path / "r" / f"{i}.txt", str(i).encode())
    monkeypatch.setattr(indexer_module, "BATCH", 2)
    seen: list[int] = []
    with Database(":memory:") as db:
        Indexer(db, Scanner(), progress=seen.append).scan(str(tmp_path / "r"))
        Indexer(db, Scanner()).scan(str(tmp_path / "r"))
    assert seen == [2, 4]
    assert utc_now().endswith("+00:00")


def test_summary_line_defaults() -> None:
    """A fresh summary renders without missing check."""
    assert ScanSummary(1, "/r").line() == ("scan done: 0 files, 0 new contents, 0 new paths, "
                                           "0 changed, 0 unchanged, missing not checked, "
                                           "0 errors")


def test_cli_scan_and_status(tree: Path, tmp_path: Path,
                             capsys: pytest.CaptureFixture[str]) -> None:
    """scan registers the files in $FILETAG_HOME/filetag.db, status summarises it.

    Args:
        tree: Test archive.
        tmp_path: pytest fixture with an empty folder.
        capsys: pytest fixture capturing output.
    """
    cli = Cli(home=Home({"FILETAG_HOME": str(tmp_path / "home")}))
    assert cli.run(["status"]) == 0
    assert "files:    none" in capsys.readouterr().out
    assert cli.run(["scan", str(tree), "--ext", "mp4", "--exclude-ext", ".jpg"]) == 0
    out = capsys.readouterr().out
    assert "scan done: 2 files, 1 new contents, 2 new paths" in out
    assert str(tmp_path / "home" / "filetag.db") in out
    assert cli.run(["status"]) == 0
    out = capsys.readouterr().out
    assert "files:    video 1" in out and "paths:    2 present, 0 missing" in out
    assert "last run: 1 scan done" in out


def test_cli_scan_inside_root_errors_and_bad_root(tree: Path,
                                                  capsys: pytest.CaptureFixture[str],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """A database inside the root is not scanned; errors give 1, a bad root 2.

    Args:
        tree: Test archive.
        capsys: pytest fixture capturing output.
        monkeypatch: pytest fixture replacing os.lstat.
    """
    db = str(tree / "b" / "index.db")
    assert Cli().run(["scan", str(tree), "--db", db]) == 0
    assert "6 files" in capsys.readouterr().out
    real = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p: (_ for _ in ()).throw(
        PermissionError(13, "Permission denied", p)) if p.endswith(".flac") else real(p))
    assert Cli().run(["scan", str(tree), "--db", db]) == 1
    captured = capsys.readouterr()
    assert "cannot read" in captured.err and "talk.flac" in captured.err
    assert Cli().run(["scan", str(tree / "nowhere"), "--db", db]) == 2
    assert "not a folder" in capsys.readouterr().err
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version = 99")
    conn.close()
    assert Cli().run(["status", "--db", db]) == 2
    assert "newer" in capsys.readouterr().err
