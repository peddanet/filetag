"""One description of a frame, produced by a worker."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from filetag_protocol.errors import ProtocolError
from filetag_protocol.fields import Fields


@dataclass(frozen=True)
class Caption:
    """Text generated for one frame of a file.

    Attributes:
        index: Position of the frame in the analysis, starting at 0.
        time_s: Position in the file in seconds.
        thinking: Whether the model was asked to think first.
        text: The description.
        watermarks: Visible marks, logos or addresses the model reported.
        seconds: Time the model needed.
        tokens: Number of generated tokens.
    """

    index: int
    time_s: float
    thinking: bool
    text: str
    watermarks: list[str] = field(default_factory=list)
    seconds: float = 0.0
    tokens: int = 0

    @classmethod
    def from_dict(cls, data: Any) -> Caption:
        """Build a caption from decoded JSON.

        Args:
            data: Decoded JSON value.

        Returns:
            The caption.

        Raises:
            ProtocolError: A field is missing or has the wrong type.
        """
        fields = Fields(data, "caption")
        marks = fields.get("watermarks", list, required=False) or []
        if not all(isinstance(mark, str) for mark in marks):
            raise ProtocolError("caption: watermarks must be strings")
        return cls(index=fields.get("index", int),
                   time_s=float(fields.get("time_s", (int, float))),
                   thinking=fields.get("thinking", bool), text=fields.get("text", str),
                   watermarks=marks,
                   seconds=float(fields.get("seconds", (int, float), required=False) or 0),
                   tokens=fields.get("tokens", int, required=False) or 0)
