"""Tests of the job and result format."""
import json

import pytest

from filetag_protocol import PROTOCOL_VERSION, Job, ProtocolError, Result

JOB_ID = "0123456789abcdef0123456789abcdef"
SHA = "a" * 64


def make_job(**changes: object) -> Job:
    """Build a valid job with optional changes.

    Args:
        **changes: Fields to override.

    Returns:
        The job.
    """
    values = {"job_id": JOB_ID, "kind": "video", "size": 10, "sha256": SHA}
    values.update(changes)
    return Job(**values)


def test_job_round_trip():
    """A job survives serialisation unchanged."""
    job = make_job(options={"frame_interval_s": 1})
    assert Job.from_json(job.to_json()) == job
    assert PROTOCOL_VERSION == 1


@pytest.mark.parametrize("changes", [{"job_id": "XYZ"}, {"kind": "pdf"}, {"size": -1},
                                     {"sha256": "abc"}])
def test_job_rejects_invalid_fields(changes: dict[str, object]) -> None:
    """Every invalid field is refused.

    Args:
        changes: Field values that break the job.
    """
    with pytest.raises(ProtocolError):
        make_job(**changes)


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"protocol": 2}),
                                  json.dumps({"protocol": True}),
                                  json.dumps({"protocol": 1, "job_id": JOB_ID})])
def test_job_from_json_rejects(text: str) -> None:
    """Malformed, foreign-protocol and incomplete jobs are refused.

    Args:
        text: JSON text to parse.
    """
    with pytest.raises(ProtocolError):
        Job.from_json(text)


def test_result_round_trip_keeps_unicode():
    """A result survives serialisation, including non-ASCII text."""
    result = Result(job_id=JOB_ID, status="ok", model="ollama/qwen3-vl:8b", language="de",
                    title="Rooftop interview", story="An interview.",
                    story_de="Ein Interview über den Dächern.", tags=["interview"])
    text = result.to_json()
    assert "über" in text
    assert Result.from_json(text) == result


@pytest.mark.parametrize("values", [{"status": "done"}, {"status": "error"},
                                    {"status": "ok", "error": "boom"}])
def test_result_rejects_inconsistent_status(values: dict[str, str]) -> None:
    """Status and error text must agree.

    Args:
        values: Status and error fields.
    """
    with pytest.raises(ProtocolError):
        Result(job_id=JOB_ID, **values)


@pytest.mark.parametrize("text", ["{", json.dumps({"protocol": 1, "job_id": JOB_ID,
                                                   "status": "ok", "tags": [1]}),
                                  json.dumps({"protocol": 1, "job_id": 5, "status": "ok"})])
def test_result_from_json_rejects(text: str) -> None:
    """Malformed results are refused.

    Args:
        text: JSON text to parse.
    """
    with pytest.raises(ProtocolError):
        Result.from_json(text)


def test_result_from_json_defaults():
    """Optional fields default to empty values."""
    text = json.dumps({"protocol": 1, "job_id": JOB_ID, "status": "error", "error": "no ffmpeg"})
    result = Result.from_json(text)
    assert (result.tags, result.title, result.language) == ([], "", None)
