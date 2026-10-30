"""Executable consumer-owned HTTP contract. No provider internals or credentials.

The exact same release artifact and verifier are vendored in both repositories.
Only public loopback HTTP is used for provider verification. CI has no paid keys.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "1.0.0"
TOKEN = "visual-contract-test-only"


def load():
    raw = (ROOT / VERSION / "contract.json").read_bytes()
    digest = (ROOT / VERSION / "SHA256SUMS").read_text().split()[0]
    assert hashlib.sha256(raw).hexdigest() == digest, "Contract release digest mismatch"
    contract = json.loads(raw)
    assert contract["version"] == VERSION
    return contract


def immutable(base):
    """Released contract bytes cannot be silently re-baselined in a PR/push."""
    if not base or set(base) == {"0"}:
        return
    assert re.fullmatch(r"[0-9a-f]{40,64}", base), "Expected a commit SHA"
    prefix = "contracts/visual-task/"
    listing = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", base, "--", prefix], text=True)
    for name in listing.splitlines():
        if re.match(r"contracts/visual-task/\d+\.\d+\.\d+/", name):
            before = subprocess.check_output(["git", "show", f"{base}:{name}"])
            assert Path(name).is_file() and Path(name).read_bytes() == before, f"Immutable release changed: {name}"


def expand(value, bindings):
    if isinstance(value, dict):
        return {key: expand(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, bindings) for item in value]
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{([a-z_]+)\}", value)
        if match:
            return bindings[match[1]]
        return re.sub(r"\$\{([a-z_]+)\}", lambda m: str(bindings[m[1]]), value)
    return value


def at(value, path):
    for segment in path.split("."):
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


def subset(expected, actual, path="body"):
    """Response extension fields are allowed; consumed fields cannot disappear."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        for key, value in expected.items():
            assert key in actual, f"{path}.{key} missing"
            subset(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual), path
        for index, (left, right) in enumerate(zip(expected, actual)):
            subset(left, right, f"{path}.{index}")
    elif type(expected) in {int, float}:
        assert type(actual) in {int, float} and expected == actual, f"{path}: expected {expected!r}, got {actual!r}"
    else:
        assert type(actual) is type(expected) and expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


def check_response(step, status, body, bindings):
    assert status == step.get("status", 200), f"{step['name']}: expected HTTP {step.get('status', 200)}, got {status}: {body}"
    if step.get("binary"):
        assert isinstance(body, bytes) and len(body) == bindings["asset_size"]
        assert hashlib.sha256(body).hexdigest() == bindings["asset_sha"]
        assert body.startswith(b"\x89PNG\r\n\x1a\n")
        return
    for name, path in step.get("capture", {}).items():
        value = at(body, path)
        if name.endswith("_id"):
            assert isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value)
        elif name == "asset_sha":
            assert isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        elif name == "asset_size":
            assert type(value) is int and 0 < value <= 20 * 1024 * 1024
        bindings[name] = value
    subset(expand(step.get("expect", {}), bindings), body, step["name"])
    for path, values in step.get("one_of", {}).items():
        assert at(body, path) in values, f"{step['name']}.{path}: unsupported value"


class Replay:
    """Strict request transcript / minimum supported response, for actual clients."""

    def __init__(self, contract=None):
        self.contract = copy.deepcopy(contract or load())
        self.bindings = self.contract["fixture_bindings"].copy()
        self.steps = [s for s in self.contract["steps"] if s.get("consumer", True)]
        self.index = 0

    def handle(self, method, path, headers, body):
        assert self.index < len(self.steps), f"Unexpected extra request: {method} {path}"
        step = self.steps[self.index]
        self.index += 1
        assert method == step["method"] and path == "/v1" + expand(step["path"], self.bindings), step["name"]
        assert headers.get("authorization") == f"Bearer {TOKEN}", "Missing service authentication"
        assert headers.get("x-api-version") == VERSION, "Missing protocol version"
        assert headers.get("x-request-id"), "Missing trace identity"
        if step.get("key"):
            assert headers.get("idempotency-key") == step["key"]
        # Request equality deliberately catches undeclared buyer data and scope changes.
        expected_body = expand(step.get("body"), self.bindings)
        try:
            subset(expected_body, body)
            subset(body, expected_body)
        except AssertionError as error:
            raise AssertionError(f"{step['name']}: request contract changed") from error
        result = (base64.b64decode(self.contract["fixture_png"]) if step.get("binary")
                  else expand(step["fixture"], self.bindings))
        check_response(step, step.get("status", 200), result, self.bindings)
        return step.get("status", 200), result

    def complete(self):
        assert self.index == len(self.steps), f"Only {self.index}/{len(self.steps)} requests exercised"


def provider(url):
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", url), "Verifier only permits an isolated loopback service"
    contract = load()
    bindings = contract["fixture_bindings"].copy()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for step in contract["steps"]:
        headers = {"Authorization": f"Bearer {TOKEN}", "X-API-Version": VERSION, "X-Request-ID": step["name"]}
        headers.update(step.get("headers", {}))
        if step.get("key"):
            headers["Idempotency-Key"] = step["key"]
        body = expand(step.get("body"), bindings)
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url + "/v1" + expand(step["path"], bindings), data, headers, method=step["method"])
        deadline = time.monotonic() + 30
        while True:
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.status
                raw = response.read(20 * 1024 * 1024 + 1)
            result = raw if step.get("binary") else json.loads(raw)
            if step.get("poll") and status == 200 and result.get("status") in {"queued", "running", "qa_pending"}:
                assert time.monotonic() < deadline, "Batch failed to reach review_pending"
                time.sleep(0.1)
                continue
            break
        check_response(step, status, result, bindings)
        print(f"PASS {step['name']}")
    print(f"Provider: {len(contract['steps'])} HTTP interactions passed; protocol {VERSION}; cost USD 0.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--url")
    args = parser.parse_args()
    load()
    immutable(args.base)
    if args.url:
        provider(args.url)
    else:
        print(f"Contract {VERSION}: release integrity and baseline passed")
