"""Command line of the controller (``filetag``)."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from filetag_core import __version__
from filetag_core.database import Database
from filetag_core.flatname import FlatNamer
from filetag_core.home import Home
from filetag_core.indexer import Indexer
from filetag_core.language import LanguageTagger
from filetag_core.scanner import Scanner


class Cli:
    """Parses arguments and runs a sub-command.

    Attributes:
        tagger: Language rules.
        namer: Flat-view name builder.
        home: Data folder of the installation.
    """

    def __init__(self, tagger: LanguageTagger | None = None, namer: FlatNamer | None = None,
                 home: Home | None = None):
        """Inject the collaborators.

        Args:
            tagger: Language rules; default ``LanguageTagger()``.
            namer: Name builder; default ``FlatNamer()``.
            home: Data folder; default ``Home()`` (``$FILETAG_HOME``).
        """
        self.tagger = tagger or LanguageTagger()
        self.namer = namer or FlatNamer()
        self.home = home or Home()

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        """Build the argument parser.

        Returns:
            The parser.
        """
        parser = argparse.ArgumentParser(
            prog="filetag", description="Describe and tag files with AI models; "
            "publish them in a flat view.")
        parser.add_argument("--version", action="version", version=f"filetag {__version__}")
        sub = parser.add_subparsers(dest="command", required=True)
        name = sub.add_parser("name", help="show the flat-view name for a title")
        name.add_argument("title", help="descriptive title")
        name.add_argument("--lang", default=None, help="ISO 639-1 code of the speech")
        name.add_argument("--id", dest="file_id", required=True, help="hex id of the file")
        name.add_argument("--ext", default="", help="extension including the dot")
        scan = sub.add_parser("scan", help="register all files below a folder in the database")
        scan.add_argument("root", help="folder to scan; the files are only read, never changed")
        scan.add_argument("--ext", action="append", dest="include", metavar="EXT",
                          help="only files with this extension (repeatable); default: all")
        scan.add_argument("--exclude-ext", action="append", dest="exclude", default=[],
                          metavar="EXT", help="never files with this extension (repeatable)")
        scan.add_argument("--db", default=None, help="database file; default "
                          "$FILETAG_HOME/filetag.db")
        status = sub.add_parser("status", help="summarise the database")
        status.add_argument("--db", default=None, help="database file")
        return parser

    def _db_path(self, given: str | None) -> str:
        """Choose the database file.

        Args:
            given: Value of ``--db`` or None.

        Returns:
            Path of the database file; the data folder is created if needed.
        """
        if given:
            return given
        self.home.ensure()
        return str(self.home.database)

    def scan(self, args: argparse.Namespace) -> int:
        """Run the ``scan`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0 clean, 1 with unreadable files or interrupted.
        """
        path = self._db_path(args.db)
        scanner = Scanner(include=args.include, exclude=args.exclude,
                          skip_paths=[path, path + "-journal", path + "-wal", path + "-shm"])
        with Database(path) as db:
            summary = Indexer(db, scanner, progress=lambda n: print(
                f"... {n} files", file=sys.stderr, flush=True)).scan(args.root)
        for where, message in summary.errors:
            print(f"filetag: cannot read {where}: {message}", file=sys.stderr)
        print(summary.line())
        print(f"database: {path}")
        return 1 if summary.errors or summary.aborted else 0

    def status(self, args: argparse.Namespace) -> int:
        """Run the ``status`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0.
        """
        path = self._db_path(args.db)
        with Database(path) as db:
            info = db.status()
        files = info["files"]
        print(f"database: {path} (schema {info['schema']})")
        print("files:    " + (", ".join(f"{k} {v}" for k, v in files.items()) or "none"))
        print(f"paths:    {info['paths']} present, {info['missing']} missing")
        last = info["last_run"]
        print("last run: " + ("none" if last is None else " ".join(str(v) for v in last)))
        return 0

    def run(self, argv: Sequence[str]) -> int:
        """Run the command line.

        Args:
            argv: Arguments without the program name.

        Returns:
            Exit code.
        """
        args = self.parser().parse_args(list(argv))
        try:
            if args.command == "scan":
                return self.scan(args)
            if args.command == "status":
                return self.status(args)
            tag = self.tagger.title_tag(args.lang)
            print(self.namer.build(args.title, tag, args.file_id, args.ext))
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"filetag: {exc}", file=sys.stderr)
            return 2
        return 0


def main() -> int:
    """Console entry point.

    Returns:
        Exit code.
    """
    return Cli().run(sys.argv[1:])
