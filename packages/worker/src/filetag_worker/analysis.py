"""From a video in the work area to frame captions, title and description."""
from __future__ import annotations

import base64
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filetag_protocol import Caption, Job, Result
from filetag_worker.errors import FlaggedContent, WorkerError
from filetag_worker.media import MediaTools
from filetag_worker.ollama import OllamaClient

DEFAULT_MODEL = "qwen3.8:27b"
DEFAULT_CAPTION_PROMPT = (
    "Describe this video frame factually for a private searchable archive, in English, in two "
    "to four sentences. Name the number of people, their clothing, what they are doing, the "
    "setting, notable objects and visible text. Do not judge or add warnings."
)
DEFAULT_SUMMARY_PROMPT = (
    "Summarise these time-stamped descriptions of one video factually and concisely, in "
    "English. Keep names of actions, people count, places and visible text; do not invent "
    "anything."
)
CAPTION_FORMAT = (
    " If any person shown could be under 18, answer only with the word FLAGGED and describe "
    "nothing. Otherwise answer in exactly two lines:\n"
    "DESCRIPTION: <the description>\n"
    "WATERMARKS: <visible watermarks, logos or web addresses separated by semicolons, or NONE>"
)
FINAL_INSTRUCTION = (
    " Answer with a short descriptive title, a readable description of two to five sentences "
    "and up to ten lower-case search tags."
)
FINAL_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "story": {"type": "string"},
                   "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "story", "tags"],
}
NUM_CTX = 8192
LIMIT_PLAIN = 512
LIMIT_THINKING = 2048
LIMIT_SUMMARY = 1024
CHUNK = 30
NANOSECONDS = 1e9
_ANSWER = re.compile(r"DESCRIPTION:\s*(?P<text>.*?)\s*(?:WATERMARKS:\s*(?P<marks>.*))?$",
                     re.IGNORECASE | re.DOTALL)
_REFUSAL = re.compile(r"^\s*(i'?m sorry|sorry|i can'?t|i cannot|i am unable|i'?m unable|"
                      r"i won'?t|i will not)", re.IGNORECASE)
Progress = Callable[[dict[str, Any]], None]


def parse_caption(text: str) -> tuple[str, list[str]]:
    """Split an answer into description and watermarks.

    Args:
        text: Generated answer.

    Returns:
        Description and reported marks; without the labels the whole answer
        counts as description.
    """
    match = _ANSWER.search(text.strip())
    if match is None:
        return text.strip(), []
    marks = (mark.strip() for mark in re.split(r"[;\n]+", match.group("marks") or ""))
    return match.group("text").strip(), [m for m in marks if m and m.upper() != "NONE"]


def confirmed_marks(captions: list[Caption]) -> list[str]:
    """Keep the marks that several frames agree on.

    Frames analysed with thinking read text more reliably, so they decide
    when there are any; a mark needs at least half of them. Without such a
    result a mark must appear in at least two frames.

    Args:
        captions: All captions.

    Returns:
        Confirmed marks, most frequent first.
    """
    careful = [caption for caption in captions if caption.thinking and caption.watermarks]
    votes = Counter(mark for caption in careful for mark in set(caption.watermarks))
    needed = max(1, math.ceil(len(careful) / 2))
    found = [mark for mark, count in votes.most_common() if count >= needed]
    if found:
        return found
    votes = Counter(mark for caption in captions for mark in set(caption.watermarks))
    return [mark for mark, count in votes.most_common() if count >= 2]


@dataclass(frozen=True)
class Settings:
    """Analysis options of one job.

    Attributes:
        model: Model name.
        interval_s: Seconds between frames.
        think_every: Every n-th frame uses thinking; 0 never, 1 always.
        max_frames: Upper limit of frames; 0 means none.
        caption_prompt: Instruction for one frame.
        summary_prompt: Instruction for condensing text.
    """

    model: str = DEFAULT_MODEL
    interval_s: float = 5.0
    think_every: int = 6
    max_frames: int = 0
    caption_prompt: str = DEFAULT_CAPTION_PROMPT
    summary_prompt: str = DEFAULT_SUMMARY_PROMPT

    @classmethod
    def from_options(cls, options: Mapping[str, int | float | str]) -> Settings:
        """Read and check the options of a job.

        Args:
            options: Options of the job.

        Returns:
            The settings.

        Raises:
            WorkerError: A value is outside its range.
        """
        try:
            made = cls(model=str(options.get("model", DEFAULT_MODEL)),
                       interval_s=float(options.get("interval_s", 5.0)),
                       think_every=int(options.get("think_every", 6)),
                       max_frames=int(options.get("max_frames", 0)),
                       caption_prompt=str(options.get("caption_prompt", DEFAULT_CAPTION_PROMPT)),
                       summary_prompt=str(options.get("summary_prompt", DEFAULT_SUMMARY_PROMPT)))
        except ValueError as exc:
            raise WorkerError(f"invalid job option: {exc}") from exc
        if made.interval_s <= 0 or made.think_every < 0 or made.max_frames < 0:
            raise WorkerError("invalid job option: values out of range")
        return made

    def times(self, duration: float) -> list[float]:
        """Choose the frame positions.

        Args:
            duration: Length of the video in seconds.

        Returns:
            Positions in seconds, centred in equal sections.
        """
        count = max(1, math.ceil(duration / self.interval_s))
        if self.max_frames:
            count = min(count, self.max_frames)
        step = duration / count
        return [(index + 0.5) * step for index in range(count)]

    def wants_thinking(self, index: int) -> bool:
        """Tell whether a frame is analysed with thinking.

        Args:
            index: Frame position in the analysis.

        Returns:
            True for every ``think_every``-th frame, starting with the first.
        """
        return self.think_every > 0 and index % self.think_every == 0


class Analyzer:
    """Runs the model calls of one job.

    Attributes:
        client: Ollama client.
        media: Media programs.
        progress: Receives progress events without any content.
    """

    def __init__(self, client: OllamaClient, media: MediaTools,
                 progress: Progress = lambda event: None):
        """Inject the collaborators.

        Args:
            client: Ollama client.
            media: Media programs.
            progress: Receiver of progress events.
        """
        self.client = client
        self.media = media
        self.progress = progress

    def _caption(self, settings: Settings, capable: bool, index: int, second: float,
                 frame: Path, counters: Counter[str]) -> Caption | None:
        """Describe one frame.

        Args:
            settings: Analysis options.
            capable: Whether the model supports the thinking switch.
            index: Frame position in the analysis.
            second: Position in the video.
            frame: JPEG file.
            counters: Statistics to update.

        Returns:
            The caption, or None when the model gave no usable answer.

        Raises:
            FlaggedContent: The model flagged the frame.
        """
        wanted = settings.wants_thinking(index)
        limit = LIMIT_THINKING if wanted else LIMIT_PLAIN
        answer = self.client.generate(
            settings.model, settings.caption_prompt + CAPTION_FORMAT,
            {"num_ctx": NUM_CTX, "num_predict": limit, "temperature": 0.2, "seed": 42},
            image=base64.b64encode(frame.read_bytes()).decode(),
            think=wanted if capable else None)
        raw = str(answer.get("response", "")).strip()
        if raw.upper().startswith("FLAGGED"):
            raise FlaggedContent("a frame was flagged; the file needs a review by a person")
        counters["leak"] += int(not wanted and bool(answer.get("thinking")))
        counters["refused"] += int(bool(_REFUSAL.match(raw)))
        text, marks = parse_caption(raw)
        if not text or _REFUSAL.match(text):
            counters["empty"] += 1
            return None
        return Caption(index, round(second, 3), wanted, text, marks,
                       round(answer.get("total_duration", 0) / NANOSECONDS, 3),
                       int(answer.get("eval_count", 0)))

    def _summarise(self, settings: Settings, text: str, capable: bool) -> str:
        """Condense text with the model.

        Args:
            settings: Analysis options.
            text: Text to condense.
            capable: Whether the model supports the thinking switch.

        Returns:
            The summary.
        """
        answer = self.client.generate(
            settings.model, f"{settings.summary_prompt}\n\n{text}",
            {"num_ctx": NUM_CTX, "num_predict": LIMIT_SUMMARY, "temperature": 0.2, "seed": 42},
            think=False if capable else None)
        return str(answer.get("response", "")).strip()

    def _final(self, settings: Settings, material: str, capable: bool) -> dict[str, Any] | None:
        """Ask for title, description and tags as JSON.

        Args:
            settings: Analysis options.
            material: Condensed text of the video.
            capable: Whether the model supports the thinking switch.

        Returns:
            The decoded fields, or None after two unusable answers.
        """
        prompt = f"{settings.summary_prompt}{FINAL_INSTRUCTION}\n\n{material}"
        for _ in range(2):
            answer = self.client.generate(
                settings.model, prompt,
                {"num_ctx": NUM_CTX, "num_predict": LIMIT_SUMMARY, "temperature": 0.2,
                 "seed": 42}, think=False if capable else None, schema=FINAL_SCHEMA)
            try:
                data = json.loads(str(answer.get("response", "")))
            except ValueError:
                continue
            if (isinstance(data, dict) and isinstance(data.get("title"), str)
                    and isinstance(data.get("story"), str)
                    and isinstance(data.get("tags"), list)):
                return data
        return None

    def _describe(self, settings: Settings, captions: list[Caption],
                  capable: bool) -> tuple[str, str, list[str]]:
        """Condense the captions step by step.

        Args:
            settings: Analysis options.
            captions: Frame captions.
            capable: Whether the model supports the thinking switch.

        Returns:
            Title, description and tags; empty title when no valid answer came.
        """
        lines = [f"[{caption.time_s:.0f} s] {caption.text}" for caption in captions]
        blocks = ["\n".join(lines[start:start + CHUNK])
                  for start in range(0, len(lines), CHUNK)]
        parts = blocks
        if len(blocks) > 1:
            parts = []
            for index, block in enumerate(blocks):
                self.progress({"event": "summary", "done": index, "total": len(blocks)})
                parts.append(self._summarise(settings, block, capable))
        material = "\n\n".join(parts)
        data = self._final(settings, material, capable)
        if data is None:
            return "", material, []
        tags = [str(tag).strip().lower() for tag in data["tags"] if str(tag).strip()]
        return data["title"].strip(), data["story"].strip(), tags

    def run(self, job: Job, video: Path, folder: Path) -> Result:
        """Analyse one video.

        Args:
            job: The job.
            video: Video file in the work area.
            folder: Job folder for temporary frames.

        Returns:
            The result with status ``ok``.

        Raises:
            WorkerError: The model is unsuitable or gave no usable caption.
        """
        settings = Settings.from_options(job.options)
        features = self.client.capabilities(settings.model)
        if "vision" not in features:
            raise WorkerError(f"model {settings.model} cannot read images")
        capable = "thinking" in features
        times = settings.times(self.media.duration(video))
        captions: list[Caption] = []
        counters: Counter[str] = Counter()
        for index, second in enumerate(times):
            self.progress({"event": "frame", "done": index, "total": len(times)})
            frame = self.media.frame(video, second, folder / f"frame-{index:06d}.jpg")
            caption = self._caption(settings, capable, index, second, frame, counters)
            frame.unlink()
            if caption is not None:
                captions.append(caption)
        if not captions:
            raise WorkerError("the model gave no usable description")
        self.progress({"event": "summary", "done": 0, "total": 1})
        title, story, tags = self._describe(settings, captions, capable)
        stats: dict[str, int | float] = {
            "frames": len(times), "captions": len(captions), "empty": counters["empty"],
            "refused": counters["refused"], "leak": counters["leak"],
            "thinking": sum(caption.thinking for caption in captions),
            "caption_s": round(sum(caption.seconds for caption in captions), 3)}
        return Result(job.job_id, "ok", model=f"ollama/{settings.model}", title=title,
                      story=story, tags=tags, captions=captions,
                      watermarks=confirmed_marks(captions), stats=stats)
