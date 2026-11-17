"""Command line of the controller (``filetag``)."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from filetag_core import __version__
from filetag_core.flatname import FlatNamer
from filetag_core.language import LanguageTagger


class Cli:
    """Parses arguments and runs a sub-command.

    Attributes:
        tagger: Language rules.
        namer: Flat-view name builder.
    """

    def __init__(self, tagger: LanguageTagger | None = None, namer: FlatNamer | None = None):
        """Inject the collaborators.

        Args:
            tagger: Language rules; default ``LanguageTagger()``.
            namer: Name builder; default ``FlatNamer()``.
        """
        self.tagger = tagger or LanguageTagger()
        self.namer = namer or FlatNamer()

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
        return parser

    def run(self, argv: Sequence[str]) -> int:
        """Run the command line.

        Args:
            argv: Arguments without the program name.

        Returns:
            Exit code.
        """
        args = self.parser().parse_args(list(argv))
        try:
            tag = self.tagger.title_tag(args.lang)
            print(self.namer.build(args.title, tag, args.file_id, args.ext))
        except ValueError as exc:
            print(f"filetag: {exc}", file=sys.stderr)
            return 2
        return 0


def main() -> int:
    """Console entry point.

    Returns:
        Exit code.
    """
    return Cli().run(sys.argv[1:])
