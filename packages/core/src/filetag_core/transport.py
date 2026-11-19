"""Starts a worker locally or through SSH and exchanges one job with it."""
from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Any

from filetag_protocol import Job, ProtocolError, Result

LOCAL = "local"
REMOTE_WORKER = "~/.local/bin/filetag-worker"
BLOCK = 1024 * 1024
Progress = Callable[[dict[str, Any]], None]
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4")


@dataclass(frozen=True)
class WorkerTransport:
    """Way to reach one worker.

    Attributes:
        host: ``local`` or an SSH destination such as ``kirechner``.
        worker: Worker program; default depends on ``host``.
    """

    host: str = LOCAL
    worker: str | None = None

    def command(self, action: str) -> list[str]:
        """Build the command line.

        Args:
            action: Worker sub-command.

        Returns:
            Program and arguments.

        Raises:
            RuntimeError: A needed program is missing, or the host is unsafe.
        """
        if self.host == LOCAL:
            program = shutil.which(self.worker or "filetag-worker")
            if program is None:
                raise RuntimeError("filetag-worker is not installed here")
            return [program, action]
        if self.host.startswith("-"):
            raise RuntimeError(f"invalid host name: {self.host}")
        ssh = shutil.which("ssh")
        if ssh is None:
            raise RuntimeError("ssh is not installed")
        return [ssh, *SSH_OPTIONS, "--", self.host, f"{self.worker or REMOTE_WORKER} {action}"]

    def models(self) -> list[dict[str, Any]]:
        """Ask the worker for its installed models.

        Returns:
            One record per model.

        Raises:
            RuntimeError: The worker cannot be reached or gives no valid list.
        """
        done = subprocess.run(self.command("models"), capture_output=True,  # nosec B603
                              text=True, check=False)
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip() or "the worker gave no model list")
        try:
            models: list[dict[str, Any]] = json.loads(done.stdout)
        except ValueError as exc:
            raise RuntimeError("the worker gave no valid model list") from exc
        return models

    def run_job(self, job: Job, path: str, progress: Progress) -> Result:
        """Send the job and the file, then wait for the result.

        Args:
            job: The job.
            path: File to send.
            progress: Receives the progress events of the worker.

        Returns:
            The result of the worker.

        Raises:
            RuntimeError: The connection failed or no valid result arrived.
        """
        with subprocess.Popen(self.command("job"), stdin=subprocess.PIPE,  # nosec B603
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
            assert stdin and stdout and stderr  # nosec B101
            output: list[bytes] = []
            sender = threading.Thread(target=self._send, args=(job, path, stdin), daemon=True)
            reader = threading.Thread(target=lambda: output.append(stdout.read()), daemon=True)
            sender.start()
            reader.start()
            notes: list[str] = []
            try:
                for raw in stderr:
                    self._event(raw, progress, notes)
                process.wait()
            finally:
                if process.poll() is None:  # interrupted: do not leave the worker running
                    process.terminate()
            reader.join()
            sender.join(timeout=5)
        try:
            return Result.from_json(b"".join(output).decode("utf-8", errors="replace"))
        except ProtocolError as exc:
            detail = "; ".join(notes[-3:]) or str(exc)
            raise RuntimeError(f"no valid result from the worker: {detail}") from exc

    @staticmethod
    def _send(job: Job, path: str, target: IO[bytes]) -> None:
        """Write the job line and the file.

        Args:
            job: The job.
            path: File to send.
            target: Standard input of the worker.
        """
        try:
            with target, open(path, "rb") as source:
                target.write(job.to_json().encode() + b"\n")
                shutil.copyfileobj(source, target, BLOCK)
        except OSError:
            pass  # the worker ended early; its result or error text explains why

    @staticmethod
    def _event(raw: bytes, progress: Progress, notes: list[str]) -> None:
        """Handle one line of the error stream.

        Args:
            raw: The line.
            progress: Receiver of progress events.
            notes: Collects lines that are no events, such as SSH errors.
        """
        text = raw.decode("utf-8", errors="replace").strip()
        try:
            event = json.loads(text)
        except ValueError:
            event = None
        if isinstance(event, dict):
            progress(event)
        elif text:
            notes.append(text)
