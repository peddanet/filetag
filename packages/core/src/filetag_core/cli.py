"""Command line of the controller (``filetag``)."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

from filetag_core import __version__
from filetag_core.analyze import AnalysisRequest, AnalysisRun, load_prompts
from filetag_core.database import Database
from filetag_core.flatname import FlatNamer
from filetag_core.home import Home
from filetag_core.indexer import Indexer
from filetag_core.language import LanguageTagger
from filetag_core.scanner import Scanner
from filetag_core.transport import LOCAL, WorkerTransport

DEFAULT_MODEL = "qwen3.8:27b"


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
        analyze = sub.add_parser("analyze", help="describe video files with an AI model")
        analyze.add_argument("paths", nargs="+", help="video files or folders; only read")
        analyze.add_argument("--host", default=LOCAL,
                             help="SSH destination of the worker; default: this machine")
        analyze.add_argument("--worker", default=None, help="worker program on that host")
        analyze.add_argument("--model", default=DEFAULT_MODEL, help="model name")
        analyze.add_argument("--interval", type=float, default=5.0,
                             help="seconds between frames (default 5)")
        analyze.add_argument("--think-every", type=int, default=6, metavar="N",
                             help="every N-th frame with thinking; 0 never, 1 always (default 6)")
        analyze.add_argument("--max-frames", type=int, default=0,
                             help="upper frame limit per file; 0 means none")
        analyze.add_argument("--prompt", default=None, help="file with the frame instruction")
        analyze.add_argument("--summary-prompt", default=None,
                             help="file with the summary instruction")
        analyze.add_argument("--force", action="store_true",
                             help="analyse again although a result of this model exists")
        analyze.add_argument("--db", default=None, help="database file")
        models = sub.add_parser("models", help="list the models of a worker")
        models.add_argument("--host", default=LOCAL, help="SSH destination; default: this machine")
        models.add_argument("--worker", default=None, help="worker program on that host")
        show = sub.add_parser("show", help="show the newest analysis of a file")
        show.add_argument("file", help="path or start of the file id")
        show.add_argument("--captions", action="store_true", help="also print the frame texts")
        show.add_argument("--db", default=None, help="database file")
        search = sub.add_parser("search", help="search the analysed files")
        search.add_argument("query", help="search words (SQLite FTS5 syntax)")
        search.add_argument("--db", default=None, help="database file")
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

    @staticmethod
    def _progress(event: dict[str, Any]) -> None:
        """Print one progress event of the worker.

        Args:
            event: The event.
        """
        if event.get("event") in ("frame", "summary"):
            done, total = int(event.get("done", 0)) + 1, event.get("total", "?")
            print(f"... {event['event']} {done}/{total}", file=sys.stderr, flush=True)
        elif event.get("event") == "receive" and event.get("done") == 0:
            print("... sending file", file=sys.stderr, flush=True)

    def analyze(self, args: argparse.Namespace) -> int:
        """Run the ``analyze`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0 when all files are done, otherwise 1.
        """
        prompts = load_prompts(self.home, args.prompt, args.summary_prompt)
        request = AnalysisRequest(args.model, args.interval, args.think_every, args.max_frames,
                                  args.force, prompts)
        with Database(self._db_path(args.db)) as db:
            return AnalysisRun(db, WorkerTransport(args.host, args.worker), request,
                               self._progress, print).run(args.paths)

    @staticmethod
    def models(args: argparse.Namespace) -> int:
        """Run the ``models`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0.
        """
        for item in WorkerTransport(args.host, args.worker).models():
            features = ",".join(item.get("capabilities", []))
            print(f"{item.get('name', ''):<28} {item.get('size', 0) / 1e9:6.1f} GB  "
                  f"{item.get('id', ''):<12}  {features}")
        return 0

    def show(self, args: argparse.Namespace) -> int:
        """Run the ``show`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0, or 1 when nothing is known about the file.
        """
        reference = os.path.realpath(args.file) if os.path.exists(args.file) else args.file
        with Database(self._db_path(args.db)) as db:
            file_id = db.resolve(reference)
            found = db.latest_analysis(file_id or "")
        if not found:
            print("filetag: no analysis of this file", file=sys.stderr)
            return 1
        print(f"title:      {found['title']}\nmodel:      {found['model']}")
        print(f"watermarks: {', '.join(found['watermarks']) or 'none'}")
        print(f"analysed:   {found['created']}\n\n{found['story']}")
        if args.captions:
            for second, thinking, text in found["captions"]:
                print(f"\n[{second:8.1f} s{' T' if thinking else ''}] {text}")
        return 0

    def search(self, args: argparse.Namespace) -> int:
        """Run the ``search`` sub-command.

        Args:
            args: Parsed arguments.

        Returns:
            0 with hits, otherwise 1.
        """
        with Database(self._db_path(args.db)) as db:
            hits = db.search(args.query)
        for file_id, title, path in hits:
            print(f"{file_id[:8]}  {title}\n          {path}")
        return 0 if hits else 1

    def run(self, argv: Sequence[str]) -> int:
        """Run the command line.

        Args:
            argv: Arguments without the program name.

        Returns:
            Exit code.
        """
        args = self.parser().parse_args(list(argv))
        try:
            handler = {"scan": self.scan, "status": self.status, "analyze": self.analyze,
                       "models": self.models, "show": self.show,
                       "search": self.search}.get(args.command)
            if handler is not None:
                return handler(args)
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
