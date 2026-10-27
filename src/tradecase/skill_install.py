"""Synchronize canonical Skills into two project-local host directories.

No global configuration, network, subprocess or automatic conflict resolution.
Individual files use atomic replacement; an interrupted multi-file transaction
is detected via a pending marker and requires review rather than silent repair.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .util import utc_now

SKILL_NAMES = ("trade-inquiry", "buyer-research", "trade-compliance")
_HOST_ROOTS = {"codex": ".agents/skills", "claude": ".claude/skills"}
_MANIFEST = ".tradecase/skill-installation.json"
_PENDING = ".tradecase/skill-installation.pending.json"
_LOCK = ".tradecase/skill-install.lock"
_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml"}
_MAX_FILE_BYTES = 1_048_576


class SkillInstallError(ValueError):
    """Stable error code plus a project-relative diagnostic path."""


def _fail(code: str, path: str = ""):
    raise SkillInstallError(code + (": " + path if path else ""))


def _safe_path(project: Path, path: Path) -> None:
    try:
        path.relative_to(project)
    except ValueError:
        _fail("path_outside_project")
    current = path
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(metadata.st_mode):
                _fail("symlink_rejected", str(current.relative_to(project)))
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
                _fail("hardlink_rejected", str(current.relative_to(project)))
        if current == project:
            break
        current = current.parent


def _project_root(value: str | Path) -> Path:
    project = Path(value).expanduser().absolute()
    home = Path.home().absolute()
    globals_ = [home / name for name in (".codex", ".claude", ".agents")]
    if (
        project == home
        or project in home.parents
        or any(project == item or item in project.parents for item in globals_)
    ):
        _fail("global_destination_rejected")
    # Do not resolve and then forget that the supplied project path was a symlink.
    for component in [project, *project.parents]:
        if component.is_symlink():
            _fail("project_symlink_rejected")
    if not project.is_dir():
        _fail("project_directory_required")
    _safe_path(project, project / "pyproject.toml")
    if not (project / "pyproject.toml").is_file():
        _fail("project_marker_missing", "pyproject.toml")
    return project


def _read_file(project: Path, path: Path) -> bytes:
    _safe_path(project, path)
    if not path.is_file():
        _fail("regular_file_required", str(path.relative_to(project)))
    if path.stat().st_size > _MAX_FILE_BYTES:
        _fail("file_too_large", str(path.relative_to(project)))
    return path.read_bytes()


def _tree(project: Path, root: Path) -> dict[str, bytes]:
    _safe_path(project, root)
    if not root.exists():
        return {}
    if not root.is_dir():
        _fail("directory_required", str(root.relative_to(project)))
    files: dict[str, bytes] = {}
    for directory, dirs, filenames in os.walk(root, followlinks=False):
        for name in [*dirs, *filenames]:
            _safe_path(project, Path(directory) / name)
        for name in sorted(filenames):
            path = Path(directory) / name
            files[path.relative_to(root).as_posix()] = _read_file(project, path)
    return files


def _reference_path(project: Path, base: Path, raw: str) -> Path:
    value = raw
    for _ in range(4):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    if unquote(value) != value or "\\" in value or any(ord(c) < 32 for c in value):
        _fail("unsafe_reference", raw)
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return base  # external documentation only; never fetched
    if parsed.scheme or parsed.netloc or parsed.query or parsed.path.startswith("/"):
        _fail("unsafe_reference", raw)
    if not parsed.path:
        return base  # anchor in the current document
    relative = PurePosixPath(parsed.path)
    if ".." in relative.parts or ":" in parsed.path:
        _fail("unsafe_reference", raw)
    path = base / parsed.path
    _safe_path(project, path)
    if not path.is_file():
        _fail("missing_reference", str(path.relative_to(project)))
    return path


def _validate_references(project: Path, source: Path, text: str) -> None:
    # Canonical Skills use simple inline Markdown links plus explicitly labelled
    # project-root-relative inline-code references. No host-specific rewriting.
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        raw = match.group(1).strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1]
        elif re.search(r"\s", raw):
            # Titles are accepted; ambiguous/nested link syntax is not guessed.
            parts = re.fullmatch(r'(\S+)\s+["\'].*["\']', raw)
            if not parts:
                _fail("unsupported_reference_syntax", str(source.relative_to(project)))
            raw = parts.group(1)
        _reference_path(project, source.parent, raw)
    root_refs = re.findall(r"`((?:references|rules)/[^`\s]+\.(?:md|json|txt|yaml|yml))`", text)
    if root_refs and not re.search(
        r"project[- ]root[- ]relative|relative to the project root", " ".join(text.split()), re.I
    ):
        _fail("reference_base_not_declared", str(source.relative_to(project)))
    for ref in root_refs:
        _reference_path(project, project, ref)


def _sources(project: Path) -> dict[str, bytes]:
    output: dict[str, bytes] = {}
    for name in SKILL_NAMES:
        root = project / "skills" / name
        files = _tree(project, root)
        if "SKILL.md" not in files:
            _fail("missing_skill_source", name)
        try:
            text = files["SKILL.md"].decode("utf-8")
        except UnicodeError:
            _fail("invalid_skill_encoding", name)
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        fields: dict[str, str] = {}
        if match:
            for line in match.group(1).splitlines():
                parts = line.split(":", 1)
                if len(parts) != 2 or parts[0] not in {"name", "description"} or parts[0] in fields:
                    _fail("invalid_skill_frontmatter", name)
                fields[parts[0]] = parts[1].strip().strip("\"'")
        if fields.get("name") != name or not fields.get("description") or set(fields) != {"name", "description"}:
            _fail("invalid_skill_frontmatter", name)
        for relative, data in files.items():
            if Path(relative).suffix not in _SUFFIXES:
                _fail("unsupported_skill_asset", name + "/" + relative)
            try:
                decoded = data.decode("utf-8")
            except UnicodeError:
                _fail("invalid_skill_encoding", name + "/" + relative)
            if relative.endswith(".md"):
                _validate_references(project, root / relative, decoded)
            output[name + "/" + relative] = data
    return output


def _validate_hash_map(value) -> None:
    if not isinstance(value, dict):
        _fail("invalid_manifest")
    for relative, digest in value.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            _fail("invalid_manifest")
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or len(path.parts) < 2
            or path.parts[0] not in SKILL_NAMES
            or ".." in path.parts
            or "\\" in relative
            or ":" in relative
            or "%" in relative
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            _fail("invalid_manifest")
    if any(name + "/SKILL.md" not in value for name in SKILL_NAMES):
        _fail("invalid_manifest")


def _manifest(project: Path) -> dict:
    path = project / _MANIFEST
    _safe_path(project, path)
    if not path.exists():
        return {"schema_version": "1.0", "scope": "project", "hosts": {}}
    try:
        value = json.loads(_read_file(project, path))
    except (json.JSONDecodeError, UnicodeError):
        _fail("invalid_manifest")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or value.get("scope") != "project"
        or not isinstance(value.get("hosts"), dict)
        or set(value) - {"schema_version", "scope", "hosts", "updated_at"}
    ):
        _fail("invalid_manifest")
    for host, entry in value["hosts"].items():
        if (
            host not in _HOST_ROOTS
            or not isinstance(entry, dict)
            or set(entry) != {"source_hashes", "installed_hashes"}
        ):
            _fail("invalid_manifest")
        _validate_hash_map(entry["source_hashes"])
        _validate_hash_map(entry["installed_hashes"])
        if entry["source_hashes"] != entry["installed_hashes"]:
            _fail("invalid_manifest")
    return value


def _hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}


def _preflight(
    project: Path, targets: list[str], sources: dict[str, bytes], manifest: dict
) -> list[tuple[Path, bytes]]:
    changes: list[tuple[Path, bytes]] = []
    for host in targets:
        destination = project / _HOST_ROOTS[host]
        _safe_path(project, destination)
        prior = manifest["hosts"].get(host)
        existing = {}
        for name in SKILL_NAMES:
            root = destination / name
            _safe_path(project, root)
            if root.exists() and prior is None:
                _fail("unmanaged_skill_conflict", str(root.relative_to(project)))
            existing.update({name + "/" + relative: data for relative, data in _tree(project, root).items()})
        old_hashes = prior["installed_hashes"] if prior else {}
        if prior and _hashes(existing) != old_hashes:
            _fail("installed_skill_drift", _HOST_ROOTS[host])
        if set(old_hashes) - set(sources):
            _fail("source_file_removed_manual_review_required", _HOST_ROOTS[host])
        for relative, data in sorted(sources.items()):
            path = destination / relative
            _safe_path(project, path)
            if existing.get(relative) != data:
                changes.append((path, data))
    return changes


def _mkdirs(project: Path, directory: Path, created: list[Path]) -> None:
    if directory == project:
        return
    _safe_path(project, directory)
    if directory.exists():
        if not directory.is_dir():
            _fail("directory_required", str(directory.relative_to(project)))
        return
    _mkdirs(project, directory.parent, created)
    directory.mkdir()
    created.append(directory)


def _atomic_write(project: Path, path: Path, data: bytes) -> None:
    _safe_path(project, path)
    fd, temporary_name = tempfile.mkstemp(prefix=".tradecase-install-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_path(project, path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def install_skills(project: str | Path, target: str = "both") -> dict:
    """Install/update allowlisted Skills only inside an existing project directory."""
    if target not in {"both", "codex", "claude"}:
        _fail("invalid_target")
    root = _project_root(project)
    targets = ["codex", "claude"] if target == "both" else [target]
    sources = _sources(root)
    hashes = _hashes(sources)
    for control in (_MANIFEST, _PENDING, _LOCK):
        _safe_path(root, root / control)
    if (root / _PENDING).exists():
        _fail("incomplete_installation", _PENDING)
    if (root / _LOCK).exists():
        _fail("installation_locked", _LOCK)
    manifest = _manifest(root)
    # Preflight every target before creating even the lock/control directory.
    changes = _preflight(root, targets, sources, manifest)
    report = {
        "status": "unchanged",
        "scope": "project",
        "target": target,
        "source_hashes": hashes,
        "destinations": {host: _HOST_ROOTS[host] for host in targets},
        "changed": [],
        "manifest_ref": _MANIFEST,
    }
    if not changes and all(host in manifest["hosts"] for host in targets):
        return report
    created: list[Path] = []
    _mkdirs(root, root / ".tradecase", created)
    try:
        lock_fd = os.open(root / _LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("installation_locked", _LOCK)
    with os.fdopen(lock_fd, "w") as handle:
        handle.write(str(os.getpid()) + "\n")
    backups: dict[Path, bytes | None] = {}
    touched: list[Path] = []
    pending_written = False
    try:
        # Re-read after taking the lock; changes before lock acquisition cannot
        # use stale ownership/hash state. Lock does not protect hostile processes.
        sources = _sources(root)
        hashes = _hashes(sources)
        manifest = _manifest(root)
        changes = _preflight(root, targets, sources, manifest)
        for host in targets:
            manifest["hosts"][host] = {"source_hashes": hashes, "installed_hashes": hashes}
        manifest["updated_at"] = utc_now()
        writes = changes + [(root / _MANIFEST, _json_bytes(manifest))]
        for path, _ in writes:
            backups[path] = _read_file(root, path) if path.exists() else None
        _atomic_write(
            root,
            root / _PENDING,
            _json_bytes(
                {
                    "schema_version": "1.0",
                    "status": "incomplete_until_manifest_committed",
                    "paths": [str(path.relative_to(root)) for path, _ in writes],
                    "started_at": utc_now(),
                }
            ),
        )
        pending_written = True
        for path, data in writes:
            _mkdirs(root, path.parent, created)
            # Record before writing: even an injected I/O failure after replace
            # must restore this path during rollback.
            touched.append(path)
            _atomic_write(root, path, data)
        (root / _PENDING).unlink()
        pending_written = False
        report.update(
            status="installed", source_hashes=hashes, changed=[str(path.relative_to(root)) for path, _ in writes]
        )
        return report
    except Exception as exc:
        restored = True
        for path in reversed(touched):
            try:
                _safe_path(root, path)
                old = backups[path]
                if old is None:
                    if path.exists():
                        path.unlink()
                else:
                    _atomic_write(root, path, old)
            except Exception:
                restored = False
        if restored and pending_written:
            (root / _PENDING).unlink()
            pending_written = False
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        if not restored:
            _fail("incomplete_installation", _PENDING)
        if isinstance(exc, SkillInstallError) and not touched:
            raise
        raise SkillInstallError("installation_failed_rolled_back: " + type(exc).__name__) from exc
    finally:
        # Delete only the lock created by this invocation; a pre-existing lock
        # was rejected above and never reaches this block.
        _safe_path(root, root / _LOCK)
        (root / _LOCK).unlink()
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
