"""Command line of the worker (``filetag-worker``)."""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections.abc import Sequence

from filetag_providers import ProfileRegistry
from filetag_worker import __version__
from filetag_worker.health import Health


class WorkerCli:
    """Parses arguments and runs a sub-command.

    Attributes:
        health: Health reporter.
        registry: Provider profiles.
        today: Current date, used to judge the age of policy facts.
    """

    def __init__(self, health: Health | None = None, registry: ProfileRegistry | None = None,
                 today: datetime.date | None = None):
        """Inject the collaborators.

        Args:
            health: Health reporter; default ``Health()``.
            registry: Provider profiles; default the built-in ones.
            today: Current date; default the system date.
        """
        self.health = health or Health()
        self.registry = registry or ProfileRegistry.builtin()
        self.today = today or datetime.date.today()

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        """Build the argument parser.

        Returns:
            The parser.
        """
        parser = argparse.ArgumentParser(prog="filetag-worker",
                                         description="filetag worker on a GPU host or locally.")
        parser.add_argument("--version", action="version",
                            version=f"filetag-worker {__version__}")
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("health", help="print the health report as JSON")
        sub.add_parser("providers", help="list the model backends and their policy facts")
        return parser

    def providers(self) -> int:
        """Print one line per provider profile.

        Returns:
            0, or 1 when a profile's policy facts are stale.
        """
        stale = {p.id for p in self.registry.stale(self.today)}
        for profile in self.registry.profiles.values():
            mark = "  STALE: check policy again" if profile.id in stale else ""
            print(f"{profile.id:<11} {profile.kind:<6} {profile.adult_content:<14} "
                  f"checked {profile.policy_checked}{mark}")
        return 1 if stale else 0

    def run(self, argv: Sequence[str]) -> int:
        """Run the command line.

        Args:
            argv: Arguments without the program name.

        Returns:
            Exit code: 0 ok, 1 not ready or stale facts.
        """
        args = self.parser().parse_args(list(argv))
        if args.command == "providers":
            return self.providers()
        report = self.health.report()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1


def main() -> int:
    """Console entry point.

    Returns:
        Exit code.
    """
    return WorkerCli().run(sys.argv[1:])
