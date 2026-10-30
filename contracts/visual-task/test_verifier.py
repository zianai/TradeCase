"""Prove that the fixed gate fails on regressions, rather than only going green."""

import subprocess

import pytest
from verify import ROOT, VERSION, immutable, load, subset


def test_release_digest_and_version():
    assert load()["version"] == VERSION


@pytest.mark.parametrize("actual", [{}, {"cost": "0"}, {"cost": True}, {"cost": -1}, {"cost": 1}])
def test_missing_or_changed_numeric_contract_fails(actual):
    with pytest.raises(AssertionError):
        subset({"cost": 0}, actual)


def test_json_numbers_and_additive_fields_are_supported():
    subset({"cost": 0}, {"cost": 0.0, "optional_future_field": {"video": True}})


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_released_artifact_cannot_be_rebaselined(tmp_path, monkeypatch, change):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-q")
    artifact = tmp_path / "contracts/visual-task/1.0.0/contract.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes((ROOT / VERSION / "contract.json").read_bytes())
    git("add", ".")
    git("-c", "user.name=Contract CI", "-c", "user.email=contract@example.invalid", "commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    immutable(base)
    if change == "modify":
        artifact.write_text('{"version":"1.0.0","weakened":true}')
    else:
        artifact.unlink()
    with pytest.raises(AssertionError, match="Immutable release changed"):
        immutable(base)


def test_invalid_baseline_is_not_ignored():
    with pytest.raises(AssertionError):
        immutable("main; unsafe")
