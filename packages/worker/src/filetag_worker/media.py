"""Duration and single frames of a video through ffprobe and ffmpeg."""
from __future__ import annotations

import shutil
import subprocess  # nosec B404
from collections.abc import Callable, Sequence
from pathlib import Path

from filetag_worker.errors import WorkerError

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[bytes]"]


def run_program(command: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
    """Run a program without a shell and capture its output.

    Args:
        command: Program and arguments.

    Returns:
        The finished process.
    """
    return subprocess.run(list(command), capture_output=True, check=False)  # nosec B603


class MediaTools:
    """Wraps the two media programs.

    Attributes:
        runner: Function that runs a command.
        which: Function that locates a program.
    """

    def __init__(self, runner: Runner = run_program,
                 which: Callable[[str], str | None] = shutil.which):
        """Inject the program runner.

        Args:
            runner: Function that runs a command.
            which: Function that locates a program.
        """
        self.runner = runner
        self.which = which

    def _program(self, name: str) -> str:
        """Locate a program.

        Args:
            name: Program name.

        Returns:
            Its path.

        Raises:
            WorkerError: The program is not installed.
        """
        path = self.which(name)
        if path is None:
            raise WorkerError(f"{name} is not installed")
        return path

    def duration(self, video: Path) -> float:
        """Read the length of a video.

        Args:
            video: Video file.

        Returns:
            Duration in seconds.

        Raises:
            WorkerError: The length cannot be read.
        """
        done = self.runner([self._program("ffprobe"), "-v", "error", "-show_entries",
                            "format=duration", "-of", "default=nk=1:nw=1", str(video)])
        try:
            value = float(done.stdout.decode().strip())
        except ValueError as exc:
            raise WorkerError("the video duration cannot be read") from exc
        if done.returncode != 0 or value <= 0:
            raise WorkerError("the video has no usable duration")
        return value

    def frame(self, video: Path, second: float, target: Path) -> Path:
        """Cut one frame, at most 1280 pixels wide.

        Args:
            video: Video file.
            second: Position in seconds.
            target: JPEG file to write.

        Returns:
            The written file.

        Raises:
            WorkerError: ffmpeg produced no frame.
        """
        done = self.runner([self._program("ffmpeg"), "-loglevel", "error", "-ss",
                            f"{second:.3f}", "-i", str(video), "-frames:v", "1", "-vf",
                            "scale='min(1280,iw)':-2", "-q:v", "3", "-y", str(target)])
        if done.returncode != 0 or not target.exists():
            raise WorkerError(f"no frame could be cut at {second:.1f} s")
        return target
