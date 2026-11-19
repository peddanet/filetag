"""Minimal client for the HTTP interface of a local Ollama server."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from filetag_worker.errors import WorkerError

URL_ENV = "FILETAG_OLLAMA_URL"
DEFAULT_URL = "http://127.0.0.1:11434"
TIMEOUT_S = 900.0


class OllamaClient:
    """Talks JSON to Ollama; no other program or library is needed.

    Attributes:
        url: Server address without trailing slash.
        timeout: Timeout of one request in seconds.
    """

    def __init__(self, url: str | None = None, timeout: float = TIMEOUT_S,
                 environ: Mapping[str, str] | None = None):
        """Choose the server.

        Args:
            url: Server address; default ``$FILETAG_OLLAMA_URL`` or the local port.
            timeout: Timeout of one request in seconds.
            environ: Environment; default ``os.environ``.

        Raises:
            WorkerError: The address is not an HTTP address.
        """
        env = os.environ if environ is None else environ
        self.url = (url or env.get(URL_ENV) or DEFAULT_URL).rstrip("/")
        if urlsplit(self.url).scheme not in ("http", "https"):
            raise WorkerError(f"not an HTTP address: {self.url}")
        self.timeout = timeout

    def call(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one request.

        Args:
            path: API path.
            payload: JSON body; None sends a GET request.

        Returns:
            The decoded answer.

        Raises:
            WorkerError: The server is unreachable or reports an error.
        """
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + path, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:  # nosec B310
                answer: dict[str, Any] = json.load(reply)
                return answer
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            exc.close()
            raise WorkerError(f"Ollama answered {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise WorkerError(f"Ollama not usable at {self.url}: {exc}") from exc

    def capabilities(self, model: str) -> list[str]:
        """Read what a model can do.

        Args:
            model: Model name.

        Returns:
            Capability names such as ``vision`` and ``thinking``.
        """
        return list(self.call("/api/show", {"model": model}).get("capabilities", []))

    def models(self) -> list[dict[str, Any]]:
        """List the installed models.

        Returns:
            Name, size in bytes, short id and capabilities of every model.
        """
        return [{"name": item.get("name", ""), "size": item.get("size", 0),
                 "id": str(item.get("digest", ""))[:12],
                 "capabilities": self.capabilities(item.get("name", ""))}
                for item in self.call("/api/tags").get("models", [])]

    def generate(self, model: str, prompt: str, options: dict[str, int | float],
                 image: str | None = None, think: bool | None = None,
                 schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate text without streaming.

        Args:
            model: Model name.
            prompt: Instruction.
            options: Model options such as ``num_predict``.
            image: Base64 encoded image, if any.
            think: Thinking switch; None leaves it out.
            schema: JSON schema the answer must follow, if any.

        Returns:
            The decoded answer of the server.
        """
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False,
                                   "keep_alive": "5m", "options": options}
        if image is not None:
            payload["images"] = [image]
        if think is not None:
            payload["think"] = think
        if schema is not None:
            payload["format"] = schema
        return self.call("/api/generate", payload)
