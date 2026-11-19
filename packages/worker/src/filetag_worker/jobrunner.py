"""One job over standard input and output, locally or through SSH.

Input: one JSON line with the job, then exactly ``size`` bytes of the file.
Output: one JSON line with the result. Standard error carries progress events
as JSON lines; they never contain text about the file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from filetag_protocol import Job, ProtocolError, Result
from filetag_worker.analysis import Analyzer
from filetag_worker.errors import WorkerError
from filetag_worker.media import MediaTools
from filetag_worker.ollama import OllamaClient
from filetag_worker.workspace import Workspace

MAX_HEADER = 1024 * 1024
BLOCK = 1024 * 1024
NO_JOB = "0" * 32


class JobRunner:
    """Receives a file into the RAM work area and analyses it.

    Attributes:
        client: Ollama client.
        media: Media programs.
        root: Work root; None uses the default.
    """

    def __init__(self, client: OllamaClient | None = None, media: MediaTools | None = None,
                 root: Path | None = None, mounts: Any = None):
        """Inject the collaborators.

        Args:
            client: Ollama client; default ``OllamaClient()``.
            media: Media programs; default ``MediaTools()``.
            root: Work root; default chosen by ``Workspace``.
            mounts: Mount table reader for tests.
        """
        self.client = client or OllamaClient()
        self.media = media or MediaTools()
        self.root = root
        self.mounts = mounts

    def _workspace(self, job_id: str) -> Workspace:
        """Create the work area object.

        Args:
            job_id: Job id.

        Returns:
            The workspace.
        """
        if self.mounts is None:
            return Workspace(job_id, self.root)
        return Workspace(job_id, self.root, mounts=self.mounts)

    @staticmethod
    def _receive(job: Job, source: BinaryIO, target: Path) -> None:
        """Copy the file from the input and verify it.

        Args:
            job: The job with size and hash.
            source: Input stream.
            target: File to write.

        Raises:
            WorkerError: The file is incomplete or its hash differs.
        """
        digest = hashlib.sha256()
        left = job.size
        with target.open("xb") as output:
            target.chmod(0o600)
            while left:
                data = source.read(min(BLOCK, left))
                if not data:
                    raise WorkerError("the file arrived incomplete")
                digest.update(data)
                output.write(data)
                left -= len(data)
        if digest.hexdigest() != job.sha256:
            raise WorkerError("the file arrived damaged (hash differs)")

    def _process(self, job: Job, source: BinaryIO, log: TextIO) -> Result:
        """Run the job inside the work area.

        Args:
            job: The job.
            source: Input stream positioned at the file.
            log: Progress stream.

        Returns:
            The result.
        """
        def progress(event: dict[str, Any]) -> None:
            """Write one progress event.

            Args:
                event: The event.
            """
            log.write(json.dumps(event) + "\n")
            log.flush()

        with self._workspace(job.job_id) as space:
            space.check_space(job.size)
            progress({"event": "receive", "done": 0, "total": job.size})
            video = space.job_dir / "input"
            self._receive(job, source, video)
            progress({"event": "receive", "done": job.size, "total": job.size})
            return Analyzer(self.client, self.media, progress).run(job, video, space.job_dir)

    def run(self, source: BinaryIO, output: TextIO, log: TextIO) -> int:
        """Handle one job.

        Args:
            source: Binary input.
            output: Stream for the result line.
            log: Stream for progress events.

        Returns:
            0 when the analysis succeeded, otherwise 1.
        """
        job_id = NO_JOB
        try:
            header = source.readline(MAX_HEADER + 1)
            if len(header) > MAX_HEADER:
                raise WorkerError("the job description is too long")
            job = Job.from_json(header.decode("utf-8", errors="replace"))
            job_id = job.job_id
            result = self._process(job, source, log)
        except (ProtocolError, WorkerError, OSError) as exc:
            result = Result(job_id, "error", error=str(exc) or type(exc).__name__)
        output.write(result.to_json() + "\n")
        output.flush()
        return 0 if result.status == "ok" else 1
