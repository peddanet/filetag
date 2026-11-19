"""Sends video files to a worker and stores the results."""
from __future__ import annotations

import hashlib
import os
import socket
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from filetag_core.database import Database
from filetag_core.entry import ScanEntry
from filetag_core.filekind import KindClassifier
from filetag_core.fingerprint import Fingerprinter
from filetag_core.home import Home
from filetag_core.indexer import utc_now
from filetag_core.scanner import Scanner
from filetag_core.transport import Progress, WorkerTransport
from filetag_protocol import Job

BLOCK = 1024 * 1024
PROMPT_FILES = {"caption_prompt": "caption.txt", "summary_prompt": "summary.txt"}


@dataclass(frozen=True)
class AnalysisRequest:
    """What the user asked for.

    Attributes:
        model: Model name.
        interval_s: Seconds between frames.
        think_every: Every n-th frame with thinking; 0 never, 1 always.
        max_frames: Upper frame limit; 0 means none.
        force: Analyse again although a result of this model exists.
        prompts: Prompt texts by option name.
    """

    model: str
    interval_s: float = 5.0
    think_every: int = 6
    max_frames: int = 0
    force: bool = False
    prompts: dict[str, str] = field(default_factory=dict)

    def options(self) -> dict[str, int | float | str]:
        """Build the job options.

        Returns:
            Options; the prompts travel only inside the job, never on a command line.
        """
        return {"model": self.model, "interval_s": self.interval_s,
                "think_every": self.think_every, "max_frames": self.max_frames, **self.prompts}


def load_prompts(home: Home, caption: str | None, summary: str | None) -> dict[str, str]:
    """Read private prompt files.

    Files named on the command line win; otherwise ``prompts/caption.txt`` and
    ``prompts/summary.txt`` in the data folder are used when they exist.

    Args:
        home: Data folder.
        caption: File given for the frame prompt, or None.
        summary: File given for the summary prompt, or None.

    Returns:
        Prompt texts by job option name.
    """
    chosen = {"caption_prompt": caption, "summary_prompt": summary}
    prompts = {}
    for option, name in PROMPT_FILES.items():
        path = Path(chosen[option] or home.root / "prompts" / name)
        if chosen[option] or path.is_file():
            prompts[option] = path.read_text(encoding="utf-8").strip()
    return prompts


def full_hash(path: str) -> str:
    """Hash a whole file; the worker verifies the transfer with it.

    Args:
        path: File to read.

    Returns:
        SHA-256 as hex digits.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while data := source.read(BLOCK):
            digest.update(data)
    return digest.hexdigest()


class AnalysisRun:
    """Analyses files one after the other.

    Attributes:
        db: Database.
        transport: Way to the worker.
        request: Options of the run.
        progress: Receives worker events.
        report: Receives one line per file.
        clock: Time stamp source.
        fingerprinter: Content id.
        classifier: File kinds.
    """

    def __init__(self, db: Database, transport: WorkerTransport, request: AnalysisRequest,
                 progress: Progress, report: Callable[[str], None],
                 clock: Callable[[], str] = utc_now):
        """Inject the collaborators.

        Args:
            db: Database.
            transport: Way to the worker.
            request: Options of the run.
            progress: Receiver of worker events.
            report: Receiver of result lines.
            clock: Time stamp source.
        """
        self.db = db
        self.transport = transport
        self.request = request
        self.progress = progress
        self.report = report
        self.clock = clock
        self.fingerprinter = Fingerprinter()
        self.classifier = KindClassifier()

    def videos(self, paths: Iterable[str]) -> list[str]:
        """Expand files and folders to the video files among them.

        Args:
            paths: Files or folders.

        Returns:
            Absolute paths in stable order.

        Raises:
            FileNotFoundError: A path does not exist.
        """
        found: list[str] = []
        for given in paths:
            path = os.path.realpath(given)
            if os.path.isdir(path):
                found.extend(sorted(entry.path for entry in Scanner().walk(path)
                                    if self.classifier.classify(entry.path)[0] == "video"))
            elif os.path.isfile(path):
                found.append(path)
            else:
                raise FileNotFoundError(f"not found: {given}")
        return found

    def _register(self, path: str, run_id: int) -> str:
        """Make sure the file is known to the database.

        Args:
            path: Absolute path.
            run_id: Current run.

        Returns:
            The file id.
        """
        info = os.stat(path)
        entry = ScanEntry(path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        file_id = self.fingerprinter.digest(path, entry.size)
        now = self.clock()
        kind, mime = self.classifier.classify(path)
        self.db.add_file(file_id, entry.size, kind, mime, path, now)
        self.db.put_location(entry, file_id, run_id, now)
        return file_id

    def _one(self, path: str, run_id: int) -> bool:
        """Analyse one file.

        Args:
            path: Absolute path.
            run_id: Current run.

        Returns:
            True when the file needs no further attention.
        """
        if self.classifier.classify(path)[0] != "video":
            self.report(f"skipped, not a video: {path}")
            return True
        file_id = self._register(path, run_id)
        self.db.commit()
        if not self.request.force and self.db.has_analysis(file_id, self.request.model):
            self.report(f"already analysed: {path}")
            return True
        job = Job(uuid.uuid4().hex, "video", os.path.getsize(path), full_hash(path),
                  self.request.options())
        result = self.transport.run_job(job, path, self.progress)
        if result.status != "ok":
            self.report(f"failed: {path}: {result.error}")
            return False
        self.db.add_analysis(file_id, run_id, result, self.clock())
        self.db.commit()
        self.report(f"done: {path}: {result.title or '(no title)'}")
        return True

    def run(self, paths: Iterable[str]) -> int:
        """Analyse all given files.

        Args:
            paths: Files or folders.

        Returns:
            0 when every file is done, otherwise 1.
        """
        videos = self.videos(paths)
        run_id = self.db.start_run("analyze", socket.gethostname(), None, self.clock())
        self.db.describe_run(run_id, f"worker:{self.transport.host}", self.request.model)
        failed = 0
        status = "aborted"
        try:
            for path in videos:
                failed += int(not self._one(path, run_id))
            status = "done"
        finally:
            self.db.finish_run(run_id, status, self.clock())
        return 1 if failed else 0
