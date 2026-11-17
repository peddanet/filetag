"""Tests of the language rules, the flat-view names and the controller CLI."""
import pytest

from filetag_core import __version__
from filetag_core.cli import Cli, main
from filetag_core.flatname import FlatNamer
from filetag_core.language import LanguageTagger


@pytest.mark.parametrize("code, tag", [(None, ""), ("", ""), ("en", ""), ("EN", ""),
                                       ("de", "[de-German]"), ("pt-BR", "[pt-Portuguese]"),
                                       ("kn", "[kn-Kannada]"), ("te", "[te-Telugu]"),
                                       ("sw", "[sw]")])
def test_title_tag(code: str | None, tag: str) -> None:
    """Each language gets the tag of the owner's rules.

    Args:
        code: Detected language code.
        tag: Expected tag.
    """
    assert LanguageTagger().title_tag(code) == tag


def test_german_and_invalid_codes():
    """German gets a German text too; malformed codes are refused."""
    tagger = LanguageTagger({"de": "German"})
    assert tagger.needs_german("de_DE") and not tagger.needs_german("pt")
    with pytest.raises(ValueError):
        tagger.title_tag("123")


def test_flat_name_layout():
    """Title, tag, short id and extension appear in this order."""
    name = FlatNamer().build(" Street  food/tour.. ", "[pt-Portuguese]", "a3f9e1", ".mp4")
    assert name == "Street food tour [pt-Portuguese] [a3f9].mp4"
    assert FlatNamer().build("...", "", "beef", ".mkv") == "untitled [beef].mkv"


def test_flat_name_length_limit_keeps_utf8_intact():
    """Long titles are cut on character boundaries, the suffix stays."""
    name = FlatNamer(max_bytes=40).build("Ü" * 50, "[de-German]", "abcd", ".mp4")
    assert len(name.encode("utf-8")) <= 40
    assert name.endswith(" [de-German] [abcd].mp4")
    name.encode("utf-8").decode("utf-8")


def test_flat_name_errors():
    """Non-hex ids and oversized fixed parts are refused."""
    with pytest.raises(ValueError):
        FlatNamer().build("t", "", "xyz!", ".mp4")
    with pytest.raises(ValueError):
        FlatNamer(max_bytes=10).build("t", "[de-German]", "abcd", ".mp4")


def test_cli_name(capsys: pytest.CaptureFixture[str]) -> None:
    """The name sub-command prints the flat-view name.

    Args:
        capsys: pytest fixture capturing output.
    """
    assert Cli().run(["name", "Morning walk", "--id", "b802", "--ext", ".mp4"]) == 0
    assert capsys.readouterr().out.strip() == "Morning walk [b802].mp4"


def test_cli_error_and_main(capsys: pytest.CaptureFixture[str],
                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Errors give exit code 2; main reads sys.argv.

    Args:
        capsys: pytest fixture capturing output.
        monkeypatch: pytest fixture replacing sys.argv.
    """
    assert Cli().run(["name", "x", "--id", "nothex"]) == 2
    assert "file id" in capsys.readouterr().err
    monkeypatch.setattr("sys.argv", ["filetag", "name", "x", "--id", "abcd", "--lang", "ja"])
    assert main() == 0
    assert capsys.readouterr().out.strip() == "x [ja-Japanese] [abcd]"
    with pytest.raises(SystemExit):
        Cli().run(["--version"])
    assert __version__ in capsys.readouterr().out
