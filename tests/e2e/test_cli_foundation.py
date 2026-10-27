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
