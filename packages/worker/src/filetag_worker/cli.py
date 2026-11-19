"""Command line of the worker (``filetag-worker``)."""
from __future__ import annotations

import argparse
import datetime
import json
import signal
import sys
from collections.abc import Sequence
from types import FrameType

from filetag_providers import ProfileRegistry
from filetag_worker import __version__
from filetag_worker.errors import WorkerError
from filetag_worker.health import Health
from filetag_worker.jobrunner import JobRunner
from filetag_worker.ollama import OllamaClient


def stop_job(signum: int, _frame: FrameType | None) -> None:
    """End the process so that the work area is cleared on the way out.

    Args:
        signum: Received signal.

    Raises:
        SystemExit: Always.
    """
    raise SystemExit(128 + signum)


class WorkerCli:
    """Parses arguments and runs a sub-command.

    Attributes:
        health: Health reporter.
        registry: Provider profiles.
        today: Current date, used to judge the age of policy facts.
        runner: Handles one job from standard input.
        client: Ollama client.
    """

    def __init__(self, health: Health | None = None, registry: ProfileRegistry | None = None,
                 today: datetime.date | None = None, runner: JobRunner | None = None,
                 client: OllamaClient | None = None):
        """Inject the collaborators.

        Args:
            health: Health reporter; default ``Health()``.
            registry: Provider profiles; default the built-in ones.
            today: Current date; default the system date.
            runner: Job handler; created on demand when None.
            client: Ollama client; created on demand when None.
        """
        self.runner = runner
        self.client = client
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
        sub.add_parser("models", help="list the installed models as JSON")
        sub.add_parser("job", help="run one job: job line and file on standard input")
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

    def models(self) -> int:
        """Print the installed models.

        Returns:
            0, or 1 when the model server cannot be used.
        """
        try:
            models = (self.client or OllamaClient()).models()
        except WorkerError as exc:
            print(f"filetag-worker: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(models, sort_keys=True))
        return 0

    def job(self) -> int:
        """Run one job from standard input.

        Returns:
            0 on success, otherwise 1.
        """
        for number in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(number, stop_job)
        runner = self.runner or JobRunner()
        return runner.run(sys.stdin.buffer, sys.stdout, sys.stderr)

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
        if args.command == "models":
            return self.models()
        if args.command == "job":
            return self.job()
        report = self.health.report()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1


def main() -> int:
    """Console entry point.

    Returns:
        Exit code.
    """
    return WorkerCli().run(sys.argv[1:])
