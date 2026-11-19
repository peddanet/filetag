"""Tests of the analysis path: protocol, worker, transport, controller and CLI."""
import hashlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from filetag_core.analyze import AnalysisRequest, AnalysisRun, full_hash, load_prompts
from filetag_core.cli import Cli
from filetag_core.database import SCHEMA, Database
from filetag_core.home import Home
from filetag_core.transport import WorkerTransport
from filetag_protocol import Caption, Job, ProtocolError, Result
from filetag_worker.analysis import Analyzer, Settings, confirmed_marks, parse_caption
from filetag_worker.cli import WorkerCli, stop_job
from filetag_worker.errors import FlaggedContent, WorkerError
from filetag_worker.jobrunner import JobRunner
from filetag_worker.media import MediaTools, run_program
from filetag_worker.ollama import OllamaClient
from filetag_worker.workspace import Workspace

ANSWER = "DESCRIPTION: A person walks.\nWATERMARKS: site.example; NONE"
FINAL = json.dumps({"title": "A walk", "story": "Someone walks.", "tags": ["Walk", " "]})


class FakeOllama:
    """Scripted replacement of the Ollama client.

    Attributes:
        features: Reported capabilities.
        answers: Queue of caption answers; the last one repeats.
        finals: Queue of answers to summary requests.
        calls: Recorded requests.
    """

    def __init__(self, features: Sequence[str] = ("vision", "thinking"),
                 answers: Sequence[dict[str, Any]] | None = None,
                 finals: Sequence[str] = (FINAL,)):
        """Store the script.

        Args:
            features: Reported capabilities.
            answers: Caption answers.
            finals: Summary answers.
        """
        self.features = list(features)
        self.answers = list(answers or [{"response": ANSWER, "total_duration": 2_000_000_000,
                                         "eval_count": 9}])
        self.finals = list(finals)
        self.calls: list[dict[str, Any]] = []

    def capabilities(self, model: str) -> list[str]:
        """Return the capabilities.

        Args:
            model: Model name.

        Returns:
            The capabilities.
        """
        assert model
        return self.features

    def generate(self, model: str, prompt: str, options: dict[str, int | float],
                 image: str | None = None, think: bool | None = None,
                 schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Answer one request from the script.

        Args:
            model: Model name.
            prompt: Instruction.
            options: Model options.
            image: Image data.
            think: Thinking switch.
            schema: Answer schema.

        Returns:
            The scripted answer.
        """
        self.calls.append({"model": model, "prompt": prompt, "options": options,
                           "image": image, "think": think, "schema": schema})
        if image is not None:
            return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if schema is None:
            return {"response": "summary"}
        return {"response": self.finals.pop(0) if len(self.finals) > 1 else self.finals[0]}


class FakeMedia(MediaTools):
    """Media tools that need no real programs."""

    def duration(self, video: Path) -> float:
        """Return a fixed length.

        Args:
            video: Video file.

        Returns:
            Twelve seconds.
        """
        assert video.exists()
        return 12.0

    def frame(self, video: Path, second: float, target: Path) -> Path:
        """Write a tiny file.

        Args:
            video: Video file.
            second: Position.
            target: Target file.

        Returns:
            The target.
        """
        target.write_bytes(f"{video.name}{second}".encode())
        return target


def job_for(data: bytes, **options: int | float | str) -> Job:
    """Build a job for some bytes.

    Args:
        data: File content.
        **options: Job options.

    Returns:
        The job.
    """
    return Job("a" * 32, "video", len(data), hashlib.sha256(data).hexdigest(), options)


def ram_table(root: Path) -> str:
    """Build a mount table that declares a folder as RAM.

    Args:
        root: The folder.

    Returns:
        Text in the format of ``/proc/self/mounts``.
    """
    return f"/dev/sda1 / ext4 rw 0 0\ntmpfs {root} tmpfs rw 0 0\n"


def test_protocol_round_trip_and_checks() -> None:
    """Captions and statistics survive the JSON form; bad values are refused."""
    caption = Caption(0, 1.5, True, "text", ["mark"], 2.0, 7)
    result = Result("a" * 32, "ok", captions=[caption], watermarks=["mark"], stats={"frames": 1})
    assert Result.from_json(result.to_json()) == result
    with pytest.raises(ProtocolError, match="watermarks"):
        Caption.from_dict({"index": 0, "time_s": 1, "thinking": False, "text": "",
                           "watermarks": [1]})
    with pytest.raises(ProtocolError, match="must be int or float"):
        Caption.from_dict({"index": 0, "time_s": True, "thinking": False, "text": ""})
    bad = json.dumps({"protocol": 1, "job_id": "x", "status": "ok", "watermarks": [1]})
    with pytest.raises(ProtocolError, match="watermarks"):
        Result.from_json(bad)


def test_parse_and_confirm_marks() -> None:
    """Answers are split; careful frames decide about watermarks."""
    assert parse_caption(ANSWER) == ("A person walks.", ["site.example"])
    assert parse_caption("plain") == ("plain", [])
    careful = [Caption(i, 0.0, True, "t", ["good"]) for i in range(2)]
    fast = [Caption(2, 0.0, False, "t", ["noise"])]
    assert confirmed_marks(careful + fast) == ["good"]
    assert confirmed_marks([Caption(i, 0.0, False, "t", ["seen"]) for i in range(2)]) == ["seen"]
    assert not confirmed_marks(fast)


def test_settings() -> None:
    """Options are read, limited and turned into a frame plan."""
    plan = Settings(interval_s=5.0, max_frames=2)
    assert plan.times(20.0) == [5.0, 15.0]
    assert Settings(think_every=0).wants_thinking(0) is False
    assert Settings(think_every=2).wants_thinking(2) is True
    with pytest.raises(WorkerError, match="invalid job option"):
        Settings.from_options({"interval_s": "x"})
    with pytest.raises(WorkerError, match="out of range"):
        Settings.from_options({"interval_s": 0})


def run_analysis(tmp_path: Path, client: FakeOllama, **options: int | float | str) -> Result:
    """Analyse a fake video.

    Args:
        tmp_path: Temporary folder.
        client: Fake model server.
        **options: Job options.

    Returns:
        The result.
    """
    video = tmp_path / "input"
    video.write_bytes(b"video")
    events: list[dict[str, Any]] = []
    analyzer = Analyzer(client, FakeMedia(), events.append)  # type: ignore[arg-type]
    result = analyzer.run(job_for(b"video", **options), video, tmp_path)
    assert events and not list(tmp_path.glob("frame-*"))
    return result


def test_analyzer_mixed_thinking(tmp_path: Path) -> None:
    """Every n-th frame thinks; title, tags, marks and counters are filled.

    Args:
        tmp_path: Temporary folder.
    """
    client = FakeOllama()
    result = run_analysis(tmp_path, client, interval_s=4.0, think_every=2)
    thinks = [call["think"] for call in client.calls if call["image"]]
    assert thinks == [True, False, True]
    assert result.title == "A walk" and result.tags == ["walk"]
    assert result.watermarks == ["site.example"] and result.stats["captions"] == 3
    assert result.model == "ollama/qwen3.8:27b" and result.captions[0].seconds == 2.0


def test_analyzer_handles_poor_answers(tmp_path: Path) -> None:
    """Refusals, empty answers and a bad summary are counted, not fatal.

    Args:
        tmp_path: Temporary folder.
    """
    answers = [{"response": "I cannot do that"}, {"response": "", "thinking": "x"},
               {"response": ANSWER}]
    client = FakeOllama(features=("vision",), answers=answers, finals=("broken", "[]"))
    result = run_analysis(tmp_path, client, interval_s=4.0, think_every=0)
    assert result.stats["refused"] == 1 and result.stats["empty"] == 2
    assert result.stats["leak"] == 1 and result.title == "" and not result.tags
    assert all(call["think"] is None for call in client.calls)


def test_analyzer_long_video_is_condensed_in_steps(tmp_path: Path) -> None:
    """More captions than one block are summarised block by block.

    Args:
        tmp_path: Temporary folder.
    """
    client = FakeOllama()
    run_analysis(tmp_path, client, interval_s=0.25)
    assert sum(1 for c in client.calls if c["image"] is None and c["schema"] is None) == 2


@pytest.mark.parametrize("client,message,error", [
    (FakeOllama(features=("completion",)), "cannot read images", WorkerError),
    (FakeOllama(answers=[{"response": "FLAGGED"}]), "review", FlaggedContent),
    (FakeOllama(answers=[{"response": ""}]), "no usable", WorkerError),
])
def test_analyzer_stops(tmp_path: Path, client: FakeOllama, message: str,
                        error: type[Exception]) -> None:
    """Unsuitable models, flagged frames and empty results end the job.

    Args:
        tmp_path: Temporary folder.
        client: Fake model server.
        message: Expected error text.
        error: Expected error type.
    """
    with pytest.raises(error, match=message):
        run_analysis(tmp_path, client)


def test_media_tools(tmp_path: Path) -> None:
    """The media wrapper checks programs and their output.

    Args:
        tmp_path: Temporary folder.
    """
    def done(code: int, out: bytes = b"") -> subprocess.CompletedProcess[bytes]:
        """Build a finished process.

        Args:
            code: Exit code.
            out: Standard output.

        Returns:
            The process record.
        """
        return subprocess.CompletedProcess([], code, out, b"")

    video = tmp_path / "v"

    def found(name: str) -> str:
        """Pretend that a program exists.

        Args:
            name: Program name.

        Returns:
            Its path.
        """
        return f"/bin/{name}"

    assert MediaTools(lambda c: done(0, b"3.5\n"), found).duration(video) == 3.5
    for result in (done(0, b"x"), done(1, b"3"), done(0, b"0")):
        with pytest.raises(WorkerError):
            MediaTools(lambda c, r=result: r, found).duration(video)
    with pytest.raises(WorkerError, match="not installed"):
        MediaTools(lambda c: done(0), lambda name: None).duration(video)
    target = tmp_path / "f.jpg"
    with pytest.raises(WorkerError, match="no frame"):
        MediaTools(lambda c: done(0), found).frame(video, 1.0, target)
    target.write_bytes(b"x")
    assert MediaTools(lambda c: done(0), found).frame(video, 1.0, target) == target
    assert run_program([sys.executable, "-c", "print(1)"]).stdout.strip() == b"1"


def test_workspace(tmp_path: Path) -> None:
    """The work area is private, in RAM, exclusive and emptied.

    Args:
        tmp_path: Temporary folder.
    """
    root = tmp_path / "work"
    (root / "job-old").mkdir(parents=True)

    def table() -> str:
        """Return the mount table.

        Returns:
            Table that declares the root as RAM.
        """
        return ram_table(root)

    with Workspace("b" * 32, root, mounts=table) as space:
        assert not (root / "job-old").exists()
        assert stat.S_IMODE(root.stat().st_mode) == 0o700 and space.job_dir.is_dir()
        space.check_space(0)
        with pytest.raises(WorkerError, match="not enough"):
            space.check_space(1 << 62)
        with pytest.raises(WorkerError, match="another job"):
            with Workspace("c" * 32, root, mounts=table):
                pass
        inner = space.job_dir
    assert not inner.exists()
    with pytest.raises(WorkerError, match="RAM"):
        with Workspace("d" * 32, root, mounts=lambda: "/dev/sda1 / ext4 rw 0 0\n"):
            pass
    assert Workspace("e" * 32, environ={"FILETAG_WORK_ROOT": "/x"}).root == Path("/x")


def runner_for(tmp_path: Path, client: FakeOllama) -> JobRunner:
    """Build a job runner with fakes.

    Args:
        tmp_path: Temporary folder.
        client: Fake model server.

    Returns:
        The runner.
    """
    root = tmp_path / "ram"
    return JobRunner(client, FakeMedia(), root,  # type: ignore[arg-type]
                     lambda: ram_table(root))


def test_job_runner(tmp_path: Path) -> None:
    """A valid stream succeeds and leaves no copy; damaged input is reported.

    Args:
        tmp_path: Temporary folder.
    """
    runner = runner_for(tmp_path, FakeOllama())
    data = b"content"
    job = job_for(data)
    output, log = io.StringIO(), io.StringIO()
    stream = io.BytesIO(job.to_json().encode() + b"\n" + data)
    assert runner.run(stream, output, log) == 0
    assert Result.from_json(output.getvalue()).title == "A walk"
    assert "content" not in log.getvalue() and not list((tmp_path / "ram").glob("job-*"))
    for payload, message in ((data[:3], "incomplete"), (b"x" * len(data), "damaged")):
        output = io.StringIO()
        stream = io.BytesIO(job.to_json().encode() + b"\n" + payload)
        assert runner.run(stream, output, io.StringIO()) == 1
        assert message in (Result.from_json(output.getvalue()).error or "")
    output = io.StringIO()
    assert runner.run(io.BytesIO(b"x" * (1024 * 1024 + 2)), output, io.StringIO()) == 1
    assert "too long" in (Result.from_json(output.getvalue()).error or "")
    default = JobRunner(FakeOllama(), FakeMedia())  # type: ignore[arg-type]
    assert default._workspace("a" * 32)  # pylint: disable=protected-access


class Handler(BaseHTTPRequestHandler):
    """Small HTTP stand-in for Ollama."""

    def log_message(self, *args: Any) -> None:  # pylint: disable=arguments-differ
        """Keep the test output quiet.

        Args:
            *args: Ignored.
        """

    def reply(self, data: dict[str, Any], code: int = 200) -> None:
        """Send JSON.

        Args:
            data: Answer.
            code: HTTP status.
        """
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Answer the model list."""
        self.reply({"models": [{"name": "m:1", "size": 2_000_000_000, "digest": "abc" * 8}]})

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """Answer capabilities and generation requests."""
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if data.get("model") == "bad":
            self.reply({"error": "no"}, 404)
        elif self.path == "/api/show":
            self.reply({"capabilities": ["vision"]})
        else:
            self.reply({"response": "ok", "seen": sorted(data)})


@pytest.fixture(name="server")
def fixture_server() -> Iterator[str]:
    """Run the HTTP stand-in.

    Yields:
        Its address.
    """
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_ollama_client(server: str) -> None:
    """The client speaks the API and reports failures.

    Args:
        server: Address of the stand-in.
    """
    client = OllamaClient(server + "/")
    assert client.models()[0]["id"] == "abcabcabcabc"
    answer = client.generate("m", "p", {"seed": 1}, image="i", think=False, schema={"a": 1})
    assert {"images", "think", "format"} <= set(answer["seen"])
    with pytest.raises(WorkerError, match="404"):
        client.capabilities("bad")
    with pytest.raises(WorkerError, match="not usable"):
        OllamaClient("http://127.0.0.1:9", timeout=1).call("/x")
    with pytest.raises(WorkerError, match="not an HTTP"):
        OllamaClient(environ={"FILETAG_OLLAMA_URL": "file:///x"})


def test_worker_cli(capsys: pytest.CaptureFixture[str], server: str,
                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker lists models and hands jobs to the runner.

    Args:
        capsys: pytest fixture capturing output.
        server: Address of the stand-in.
        monkeypatch: pytest fixture.
    """
    assert WorkerCli(client=OllamaClient(server)).run(["models"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "m:1"
    assert WorkerCli(client=OllamaClient("http://127.0.0.1:9", timeout=1)).run(["models"]) == 1

    class Runner:  # pylint: disable=too-few-public-methods
        """Records that it was called."""

        def run(self, *streams: Any) -> int:
            """Accept the streams.

            Args:
                *streams: Input, output and log.

            Returns:
                Seven.
            """
            return 7 if len(streams) == 3 else 0

    monkeypatch.setattr("signal.signal", lambda *args: None)
    assert WorkerCli(runner=Runner()).run(["job"]) == 7  # type: ignore[arg-type]
    with pytest.raises(SystemExit):
        stop_job(15, None)


def fake_worker(tmp_path: Path, body: str) -> str:
    """Create an executable that acts as worker.

    Args:
        tmp_path: Temporary folder.
        body: Python code run after the arguments are read.

    Returns:
        Its path.
    """
    path = tmp_path / "fake-worker"
    path.write_text(f"#!{sys.executable}\nimport json, sys\n{body}\n", encoding="utf-8")
    path.chmod(0o700)
    return str(path)


GOOD_WORKER = """
if sys.argv[1] == "models":
    print(json.dumps([{"name": "m", "size": 1000000000, "id": "x", "capabilities": ["vision"]}]))
    raise SystemExit
job = json.loads(sys.stdin.buffer.readline())
assert len(sys.stdin.buffer.read(job["size"])) == job["size"]
print(json.dumps({"event": "frame", "done": 0, "total": 1}), file=sys.stderr, flush=True)
print("note", file=sys.stderr, flush=True)
print(json.dumps({"protocol": 1, "job_id": job["job_id"], "status": "ok", "model": "ollama/m",
                  "title": "Walk", "story": "Story", "tags": ["walk"], "watermarks": ["mark"],
                  "stats": {"frames": 1}, "captions": [{"index": 0, "time_s": 1.0,
                  "thinking": True, "text": "river", "watermarks": []}]}))
"""


def test_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Commands are built safely; job exchange and failures work.

    Args:
        tmp_path: Temporary folder.
        monkeypatch: pytest fixture.
    """
    worker = fake_worker(tmp_path, GOOD_WORKER)
    transport = WorkerTransport(worker=worker)
    assert transport.models()[0]["name"] == "m"
    data = tmp_path / "file"
    data.write_bytes(b"12345")
    events: list[dict[str, Any]] = []
    assert transport.run_job(job_for(b"12345"), str(data), events.append).title == "Walk"
    assert events == [{"event": "frame", "done": 0, "total": 1}]
    broken = WorkerTransport(worker=fake_worker(tmp_path, "print('bad note', file=sys.stderr)"))
    with pytest.raises(RuntimeError, match="bad note"):
        broken.run_job(job_for(b"12345"), str(data), events.append)
    with pytest.raises(RuntimeError, match="no valid model list"):
        broken.models()
    fail = WorkerTransport(worker=fake_worker(tmp_path, "raise SystemExit('boom')"))
    with pytest.raises(RuntimeError, match="boom"):
        fail.models()
    with pytest.raises(RuntimeError, match="invalid host"):
        WorkerTransport("-oProxy").command("job")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert WorkerTransport("kirechner").command("job")[-1] == "~/.local/bin/filetag-worker job"
    assert WorkerTransport().command("job") == ["/usr/bin/filetag-worker", "job"]
    monkeypatch.setattr("shutil.which", lambda name: None)
    for host in ("kirechner", "local"):
        with pytest.raises(RuntimeError, match="not installed"):
            WorkerTransport(host).command("job")


def test_prompts_and_hash(tmp_path: Path) -> None:
    """Private prompt files are picked up; explicit files win.

    Args:
        tmp_path: Temporary folder.
    """
    home = Home({"FILETAG_HOME": str(tmp_path)})
    assert not load_prompts(home, None, None)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "caption.txt").write_text(" own \n", encoding="utf-8")
    other = tmp_path / "s.txt"
    other.write_text("sum", encoding="utf-8")
    assert load_prompts(home, None, str(other)) == {"caption_prompt": "own",
                                                    "summary_prompt": "sum"}
    assert full_hash(str(other)) == hashlib.sha256(b"sum").hexdigest()


def test_cli_analyze_show_search_models(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole controller path stores, skips, shows and finds a result.

    Args:
        tmp_path: Temporary folder.
        capsys: pytest fixture capturing output.
        monkeypatch: pytest fixture.
    """
    monkeypatch.setenv("FILETAG_HOME", str(tmp_path / "home"))
    archive = tmp_path / "archive"
    archive.mkdir()
    video = archive / "clip.mp4"
    video.write_bytes(b"12345")
    worker = fake_worker(tmp_path, GOOD_WORKER)
    args = ["analyze", str(archive), "--worker", worker, "--model", "m"]
    assert Cli().run(args) == 0
    assert "done:" in capsys.readouterr().out
    assert Cli().run(args) == 0
    assert "already analysed" in capsys.readouterr().out
    assert Cli().run([*args, "--force"]) == 0
    assert Cli().run(["analyze", str(archive / "none"), "--worker", worker]) == 2
    capsys.readouterr()
    assert Cli().run(["show", str(video), "--captions"]) == 0
    assert "river" in capsys.readouterr().out and Cli().run(["show", "zz"]) == 1
    capsys.readouterr()
    assert Cli().run(["search", "river"]) == 0 and "Walk" in capsys.readouterr().out
    assert Cli().run(["search", "absent"]) == 1
    assert Cli().run(["search", "\""]) == 2
    assert Cli().run(["models", "--worker", worker]) == 0
    assert "vision" in capsys.readouterr().out


def test_cli_progress_and_failed_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Progress is readable; non-videos are skipped; failures set the exit code.

    Args:
        tmp_path: Temporary folder.
        capsys: pytest fixture capturing output.
    """
    Cli._progress({"event": "frame", "done": 0, "total": 2})  # pylint: disable=W0212
    Cli._progress({"event": "receive", "done": 0})  # pylint: disable=W0212
    Cli._progress({"event": "other"})  # pylint: disable=W0212
    assert "frame 1/2" in capsys.readouterr().err
    text = tmp_path / "note.txt"
    text.write_text("x", encoding="utf-8")
    video = tmp_path / "v.mkv"
    video.write_bytes(b"x")
    worker = fake_worker(tmp_path, """
job = json.loads(sys.stdin.buffer.readline())
print(json.dumps({"protocol": 1, "job_id": job["job_id"], "status": "error", "error": "nope"}))
""")
    lines: list[str] = []
    with Database(":memory:") as db:
        run = AnalysisRun(db, WorkerTransport(worker=worker), AnalysisRequest("m"),
                          lambda event: None, lines.append, clock=lambda: "now")
        assert run.run([str(text), str(video)]) == 1
        assert db.status()["last_run"][2] == "done"
    assert lines[0].startswith("skipped") and "nope" in lines[1]


def test_database_migrates_schema_one(tmp_path: Path) -> None:
    """A database of version 1 keeps its data and gains the new tables.

    Args:
        tmp_path: Temporary folder.
    """
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA + "PRAGMA user_version = 1;")
    conn.close()
    with Database(str(path)) as db:
        assert db.version() == 2 and db.resolve("nothing") is None
        assert db.latest_analysis("x") is None
    assert os.path.exists(path)
