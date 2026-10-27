import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    return subprocess.run([sys.executable, "-m", "tradecase.cli", *map(str, args)], capture_output=True, text=True)


def test_cli_init_status_validate(tmp_path):
    case = tmp_path / "inquiry"
    result = run(
        "init",
        "--inquiry",
        ROOT / "fixtures/realistic_inquiry.eml",
        "--seller",
        ROOT / "fixtures/seller_profile.json",
        "--target-country",
        "US",
        "--platform",
        "amazon_us",
        "--synthetic",
        "--out",
        case,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert run("doctor").returncode == 0
    assert run("status", "--case", case).returncode == 0
    assert run("validate", "--case", case).returncode == 0
    strict = run("validate", "--case", case, "--strict")
    assert strict.returncode == 1 and json.loads(strict.stdout)["errors"]
    assert run("send", "--case", case).returncode == 2


def test_research_and_assessment_preserve_unknowns(tmp_path):
    case = tmp_path / "unverified"
    assert (
        run(
            "init",
            "--inquiry",
            ROOT / "fixtures/realistic_inquiry.eml",
            "--seller",
            ROOT / "fixtures/seller_profile.json",
            "--synthetic",
            "--out",
            case,
        ).returncode
        == 0
    )
    prepared = run("research", "--case", case)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    assessed = run("assess", "--case", case)
    assert assessed.returncode == 0, assessed.stdout + assessed.stderr
    result = json.loads((case / "assessment.json").read_text())
    assert result["score"] is None
    assert result["decision"] == "needs_review"
    valid = run("validate", "--case", case)
    assert valid.returncode == 0, valid.stdout


def test_capture_rejects_sensitive_url_without_logging_it(tmp_path):
    case = tmp_path / "network"
    assert (
        run(
            "init",
            "--inquiry",
            ROOT / "fixtures/realistic_inquiry.eml",
            "--seller",
            ROOT / "fixtures/seller_profile.json",
            "--synthetic",
            "--out",
            case,
        ).returncode
        == 0
    )
    result = run("capture", "--case", case, "--url", "http://127.0.0.1/.env?token=should-not-leak")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "should-not-leak" not in result.stdout
    events = (case / "events.jsonl").read_text()
    assert "should-not-leak" not in events and "127.0.0.1" not in events
    manifest = json.loads((case / "manifest.json").read_text())
    assert manifest["runtime_metadata"]["network_budget"]["pages_used"] == 1
    assert manifest["runtime_metadata"]["network_budget"]["requests_used"] == 0
    assert not (case / "evidence.jsonl").exists()


def test_multiline_search_jsonl_import(tmp_path):
    case = tmp_path / "search"
    assert run("init", "--inquiry", ROOT / "fixtures/realistic_inquiry.eml", "--out", case).returncode == 0
    raw = tmp_path / "search.jsonl"
    raw.write_text('{"url":"https://www.ikea.com","title":"IKEA"}\n{"link":"https://www.ul.com","title":"UL"}\n')
    result = run(
        "import-search",
        "--case",
        case,
        "--file",
        raw,
        "--query",
        "synthetic query",
        "--captured-at",
        "2026-10-27T12:00:00Z",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = next((case / "snapshots").glob("search-*.json"))
    rows = json.loads(snapshot.read_text())
    assert len(rows) == 2 and all(r["assertion_status"] == "unverified" for r in rows)
