"""All packages of the monorepo carry the same version."""
import pathlib
import re

import filetag_core
import filetag_protocol
import filetag_providers
import filetag_worker

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_versions_agree_and_are_semver():
    """One release tag covers all four packages, so their versions must agree."""
    versions = {filetag_core.__version__, filetag_protocol.__version__,
                filetag_providers.__version__, filetag_worker.__version__}
    assert len(versions) == 1
    assert re.fullmatch(r"\d+\.\d+\.\d+", versions.pop())


def test_changelog_has_unreleased_or_current_version():
    """The change log names the current version or collects under Unreleased."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text or f"## [{filetag_core.__version__}]" in text
