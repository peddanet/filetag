"""Private work area in RAM; everything in it disappears after the job."""
from __future__ import annotations

import fcntl
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import TextIO

from filetag_worker.errors import WorkerError

ROOT_ENV = "FILETAG_WORK_ROOT"
RESERVE = 1024 ** 3
RAM_TYPES = ("tmpfs", "ramfs")


def read_mounts() -> str:
    """Read the mount table of this process.

    Returns:
        Text of ``/proc/self/mounts``.
    """
    return Path("/proc/self/mounts").read_text(encoding="utf-8")


class Workspace:
    """One job at a time in a mode-0700 folder on a RAM file system.

    Leftovers of an interrupted job are removed on entry, the job folder on
    exit. These are the only files the tool ever deletes: copies it created
    itself in RAM.

    Attributes:
        root: Folder that holds the job folders.
        mounts: Function returning the mount table.
        job_dir: Folder of the running job.
    """

    def __init__(self, job_id: str, root: Path | None = None,
                 environ: Mapping[str, str] | None = None,
                 mounts: Callable[[], str] = read_mounts):
        """Choose the folders.

        Args:
            job_id: Pseudonymous job id.
            root: Work root; default ``$FILETAG_WORK_ROOT`` or a folder in ``/dev/shm``.
            environ: Environment; default ``os.environ``.
            mounts: Function returning the mount table.
        """
        env = os.environ if environ is None else environ
        default = Path("/dev/shm") / f"filetag-worker-{os.geteuid()}"  # nosec B108
        self.root = root or Path(env.get(ROOT_ENV) or default)
        self.mounts = mounts
        self.job_dir = self.root / f"job-{job_id}"
        self._lock: TextIO | None = None

    def _check_ram(self) -> None:
        """Refuse a work root that is not in RAM.

        Raises:
            WorkerError: The folder lies on another file system type.
        """
        target = os.path.realpath(self.root)
        best = ("", "")
        for line in self.mounts().splitlines():
            parts = line.split()
            point = parts[1].replace("\\040", " ")
            inside = target == point or target.startswith(point.rstrip("/") + "/")
            if inside and len(point) >= len(best[0]):
                best = (point, parts[2])
        if best[1] not in RAM_TYPES:
            raise WorkerError("the work area is not on a RAM file system")

    def __enter__(self) -> Workspace:
        """Prepare the folder, take the lock and clear leftovers.

        Returns:
            The workspace.

        Raises:
            WorkerError: Not in RAM, foreign owner, or another job is running.
        """
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.geteuid():
            raise WorkerError("the work area belongs to another user")
        self.root.chmod(0o700)
        self._check_ram()
        lock_file = (self.root / ".lock").open("w", encoding="utf-8")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            raise WorkerError("another job is running on this worker") from exc
        self._lock = lock_file
        for old in self.root.glob("job-*"):
            shutil.rmtree(old, ignore_errors=True)
        self.job_dir.mkdir(mode=0o700)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        """Remove the job folder and release the lock.

        Args:
            exc_type: Type of a raised exception, or None.
            exc: The exception, or None.
            tb: Its traceback, or None.
        """
        shutil.rmtree(self.job_dir, ignore_errors=True)
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def check_space(self, size: int) -> None:
        """Make sure a file fits, with a reserve for the frames.

        Args:
            size: File size in bytes.

        Raises:
            WorkerError: Not enough free memory in the work area.
        """
        info = os.statvfs(self.root)
        if info.f_bavail * info.f_frsize < size + RESERVE:
            raise WorkerError("not enough free space in the RAM work area")
