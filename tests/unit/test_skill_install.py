"""Project-only installer acceptance tests; all writes use temporary projects."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from tradecase.skill_install import SKILL_NAMES, SkillInstallError, install_skills


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "tradecase-project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "tradecase"\n')
    (root / "references").mkdir()
    (root / "references" / "shared.md").write_text("Project shared SOP.\n")
    for name in SKILL_NAMES:
        directory = root / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A bounded domain skill.\n---\n\n"
            "Read `references/shared.md` (project-root-relative).\n"
        )
    return root


def snapshot_files(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def target_file(project, host="codex", name="trade-inquiry"):
    return project / (".agents" if host == "codex" else ".claude") / "skills" / name / "SKILL.md"


def test_both_targets_copy_identical_bytes_and_record_hashes(project):
    result = install_skills(project, "both")
    assert result["status"] == "installed" and result["scope"] == "project"
    manifest = json.loads((project / result["manifest_ref"]).read_text())
    for name in SKILL_NAMES:
        source = (project / "skills" / name / "SKILL.md").read_bytes()
        for host in ("codex", "claude"):
            assert target_file(project, host, name).read_bytes() == source
            assert manifest["hosts"][host]["installed_hashes"][f"{name}/SKILL.md"] == hashlib.sha256(source).hexdigest()


def test_second_run_is_byte_and_mtime_idempotent(project):
    install_skills(project, "both")
    before = snapshot_files(project)
    result = install_skills(project, "both")
    assert result["status"] == "unchanged" and result["changed"] == []
    assert snapshot_files(project) == before


def test_install_one_host_then_other_preserves_first(project):
    install_skills(project, "codex")
    before = target_file(project).stat().st_mtime_ns
    assert not (project / ".claude").exists()
    install_skills(project, "claude")
    assert target_file(project).stat().st_mtime_ns == before
    assert target_file(project, "claude").exists()


def test_unmanaged_second_target_conflict_prevents_first_install(project):
    existing = target_file(project, "claude")
    existing.parent.mkdir(parents=True)
    existing.write_text("User skill, preserve.\n")
    before = snapshot_files(project)
    with pytest.raises(SkillInstallError, match="unmanaged_skill_conflict"):
        install_skills(project, "both")
    assert not (project / ".agents").exists()
    assert snapshot_files(project) == before


def test_identical_unmanaged_file_is_still_conflict(project):
    source = project / "skills/trade-inquiry/SKILL.md"
    destination = target_file(project)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    with pytest.raises(SkillInstallError, match="unmanaged_skill_conflict"):
        install_skills(project, "codex")


@pytest.mark.parametrize("drift", ["changed", "missing", "added"])
def test_user_drift_is_preserved(project, drift):
    install_skills(project, "both")
    path = target_file(project, "claude")
    if drift == "changed":
        path.write_text("user edited this\n")
    elif drift == "missing":
        path.unlink()
    else:
        (path.parent / "personal.md").write_text("user material\n")
    before = snapshot_files(project)
    with pytest.raises(SkillInstallError, match="installed_skill_drift"):
        install_skills(project, "both")
    assert snapshot_files(project) == before


def test_source_update_only_overwrites_untouched_managed_files(project):
    install_skills(project, "both")
    source = project / "skills/trade-inquiry/SKILL.md"
    source.write_text(source.read_text() + "\nNew canonical guidance.\n")
    result = install_skills(project, "both")
    assert result["status"] == "installed"
    assert target_file(project).read_bytes() == target_file(project, "claude").read_bytes() == source.read_bytes()


def test_portable_relative_reference_is_copied(project):
    directory = project / "skills/trade-inquiry/references"
    directory.mkdir()
    (directory / "sop.md").write_text("Local SOP.\n")
    source = project / "skills/trade-inquiry/SKILL.md"
    source.write_text(source.read_text() + "\nRead [SOP](references/sop.md).\n")
    install_skills(project, "both")
    assert (target_file(project).parent / "references/sop.md").read_text() == "Local SOP.\n"


@pytest.mark.parametrize(
    "bad_reference",
    [
        "[Missing](references/missing.md)",
        "[Escape](../../outside.md)",
        "[Absolute](/etc/passwd)",
        "[Scheme](file:///etc/passwd)",
        "Read `references/missing.md` (project-root-relative).",
    ],
)
def test_broken_or_unsafe_references_fail_before_targets(project, bad_reference):
    source = project / "skills/trade-inquiry/SKILL.md"
    source.write_text(source.read_text() + "\n" + bad_reference + "\n")
    with pytest.raises(SkillInstallError):
        install_skills(project, "both")
    assert not (project / ".agents").exists()


def test_bad_frontmatter_rejected(project):
    (project / "skills/trade-inquiry/SKILL.md").write_text("---\nname: another\ndescription: bad\n---\n")
    with pytest.raises(SkillInstallError, match="invalid_skill_frontmatter"):
        install_skills(project, "both")


@pytest.mark.parametrize("target", ["user", "global", "../escape", "all", ""])
def test_unknown_target_rejected(project, target):
    with pytest.raises(SkillInstallError, match="invalid_target"):
        install_skills(project, target)


@pytest.mark.parametrize("location", ["source_file", "source_dir", "target_parent", "manifest", "root_reference"])
def test_symlink_never_followed(project, tmp_path, location):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "material.md"
    secret.write_text("must remain untouched\n")
    if location == "source_file":
        path = project / "skills/trade-inquiry/SKILL.md"
        path.unlink()
        path.symlink_to(secret)
    elif location == "source_dir":
        path = project / "skills/buyer-research"
        (path / "SKILL.md").unlink()
        path.rmdir()
        path.symlink_to(outside, target_is_directory=True)
    elif location == "target_parent":
        (project / ".agents").symlink_to(outside, target_is_directory=True)
    elif location == "manifest":
        (project / ".tradecase").mkdir()
        (project / ".tradecase/skill-installation.json").symlink_to(secret)
    else:
        path = project / "references/shared.md"
        path.unlink()
        path.symlink_to(secret)
    with pytest.raises(SkillInstallError, match="symlink"):
        install_skills(project, "both")
    assert secret.read_text() == "must remain untouched\n"


def test_hardlinked_target_is_rejected(project, tmp_path):
    install_skills(project, "codex")
    path = target_file(project)
    os.link(path, tmp_path / "alias")
    with pytest.raises(SkillInstallError, match="hardlink"):
        install_skills(project, "codex")


def test_tampered_manifest_path_rejected_without_external_write(project):
    result = install_skills(project, "codex")
    path = project / result["manifest_ref"]
    manifest = json.loads(path.read_text())
    manifest["hosts"]["codex"]["installed_hashes"]["../../escape"] = "0" * 64
    path.write_text(json.dumps(manifest))
    before = snapshot_files(project)
    with pytest.raises(SkillInstallError, match="invalid_manifest"):
        install_skills(project, "codex")
    assert snapshot_files(project) == before


def test_failed_atomic_replace_rolls_back_all_created_files(project, monkeypatch):
    real_replace = os.replace
    hit = [False]

    def fail_once(src, dst):
        if Path(dst) == target_file(project, "claude") and not hit[0]:
            hit[0] = True
            raise OSError("simulated disk fault")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_once)
    before = snapshot_files(project)
    with pytest.raises(SkillInstallError, match="installation_failed_rolled_back"):
        install_skills(project, "both")
    assert hit[0]
    assert snapshot_files(project) == before
    assert not (project / ".tradecase/skill-installation.pending.json").exists()
    assert install_skills(project, "both")["status"] == "installed"


def test_pending_or_locked_transaction_refuses_without_overwriting(project):
    control = project / ".tradecase"
    control.mkdir()
    pending = control / "skill-installation.pending.json"
    pending.write_text('{"reason":"simulated interrupted installation"}')
    with pytest.raises(SkillInstallError, match="incomplete_installation"):
        install_skills(project, "both")
    pending.unlink()
    lock = control / "skill-install.lock"
    lock.write_text("other process")
    with pytest.raises(SkillInstallError, match="installation_locked"):
        install_skills(project, "both")
    assert lock.read_text() == "other process"


def test_global_project_destination_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(SkillInstallError, match="global_destination_rejected"):
        install_skills(tmp_path, "both")
