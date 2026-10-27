"""Bounded public, read-only HTTP and inert host-output adapters.

No Agent loop, authenticated browsing, JavaScript execution, credentials, ambient
proxy, implicit Jina request or optional crawler import lives here. A successful
fetch is untrusted source material, never an automatically supported business fact.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import math
import queue
import re
import socket
import ssl
import threading
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .models import utc_timestamp
from .upstream import normalize_search
from .util import utc_now


class ReaderPolicyError(ValueError):
    """A stable policy reason; deliberately excludes sensitive URL contents."""


@dataclass(frozen=True)
class ReadPolicy:
    max_pages: int = 15
    max_requests: int = 40
    max_bytes: int = 1_048_576
    timeout_seconds: float = 15.0
    per_site_interval: float = 1.0
    max_redirects: int = 3
    user_agent: str = "TradeCase/1.0 (public read-only research)"

    def __post_init__(self):
        for key in ("max_pages", "max_requests", "max_bytes"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be a positive integer")
        if type(self.max_redirects) is not int or not 0 <= self.max_redirects <= 10:
            raise ValueError("max_redirects must be between 0 and 10")
        for key in ("timeout_seconds", "per_site_interval"):
            value = getattr(self, key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if not self.timeout_seconds or not re.fullmatch(r"[A-Za-z0-9 ./()_-]{1,160}", self.user_agent):
            raise ValueError("positive timeout and safe User-Agent required")


def _public_ip(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ReaderPolicyError("invalid_dns_address") from exc
    if (
        not ip.is_global
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    ):
        raise ReaderPolicyError("non_public_address")
    if isinstance(ip, ipaddress.IPv6Address):
        excluded = ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
        if ip.ipv4_mapped or any(ip in ipaddress.ip_network(net) for net in excluded):
            raise ReaderPolicyError("ipv6_transition_address_rejected")
    return str(ip)


@dataclass(frozen=True)
class PublicURL:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    request_target: str
    origin: str


_SENSITIVE = re.compile(
    r"(^|[/.?&=:;_-])(\.env|\.git|\.ssh|\.aws|\.config|credentials?|cookies?|"
    r"auth(?:orization)?|tokens?|api[_-]?keys?|access[_-]?keys?|passwords?|passwd|"
    r"secrets?|sessions?|signatures?|login|logout|signout|sign[-_]?in|reset[-_]?password|"
    r"password[-_]?reset|checkout|uploads?|delete|remove|unsubscribe)(?=$|[/.?&=:;_-])",
    re.I,
)
_QUERY_DENY = re.compile(
    r"token|auth|secret|password|passwd|cookie|session|signature|api.?key|access.?key|"
    r"credential|email|phone|^key$|^code$|^action$|^do$|^op$|^operation$|^command$|^cmd$",
    re.I,
)


def validate_public_url(value: str) -> PublicURL:
    """Validate syntax and literal IPs; DNS validation occurs before each hop."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ReaderPolicyError("invalid_url")
    decoded = value
    for _ in range(4):
        newer = unquote(decoded)
        if newer == decoded:
            break
        decoded = newer
    if unquote(decoded) != decoded:
        raise ReaderPolicyError("url_encoding_depth_exceeded")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in decoded) or "\\" in decoded:
        raise ReaderPolicyError("unsafe_url_characters")
    if _SENSITIVE.search(decoded) or re.search(r"eyJ[A-Za-z0-9_-]{16,}\.", decoded):
        raise ReaderPolicyError("sensitive_url_rejected")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ReaderPolicyError("http_https_only")
        if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
            raise ReaderPolicyError("url_credentials_rejected")
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if "%" in host:
            raise ReaderPolicyError("scoped_address_rejected")
        scheme = parsed.scheme.lower()
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        if port != (443 if scheme == "https" else 80):
            raise ReaderPolicyError("port_rejected")
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ReaderPolicyError):
            raise
        raise ReaderPolicyError("invalid_url") from exc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if (
            len(labels) < 2
            or len(host) > 253
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        ):
            raise ReaderPolicyError("invalid_public_hostname")
        if host.endswith(
            (".local", ".localhost", ".internal", ".home", ".lan", ".onion", ".invalid", ".test", ".example")
        ):
            raise ReaderPolicyError("non_public_hostname")
        if re.fullmatch(r"[0-9.]+", host):
            raise ReaderPolicyError("noncanonical_ip_literal")
    else:
        host = _public_ip(host)
    expanded = urlsplit(decoded)
    if ".." in expanded.path.split("/"):
        raise ReaderPolicyError("path_traversal_rejected")
    if any(_QUERY_DENY.search(key) for key, _ in parse_qsl(expanded.query, keep_blank_values=True)):
        raise ReaderPolicyError("sensitive_query_rejected")
    if re.search(r"/[a-fA-F0-9]{48,}(?:/|$)", expanded.path):
        raise ReaderPolicyError("opaque_token_path_rejected")
    # Fragments are not transmitted; rejecting all avoids leaking OAuth tokens in logs.
    if parsed.fragment:
        raise ReaderPolicyError("url_fragment_rejected")
    netloc = f"[{host}]" if ":" in host else host
    path = parsed.path or "/"
    origin = f"{scheme}://{netloc}"
    normalized = urlunsplit((scheme, netloc, path, parsed.query, ""))
    target = path + ("?" + parsed.query if parsed.query else "")
    return PublicURL(normalized, scheme, host, port, path, target, origin)


@dataclass
class ResearchBudget:
    pages_used: int = 0
    requests_used: int = 0
    origin_last_requested_at: dict[str, float] = field(default_factory=dict)
    origin_min_interval: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if (
            type(self.pages_used) is not int
            or type(self.requests_used) is not int
            or min(self.pages_used, self.requests_used) < 0
        ):
            raise ValueError("budget counters must be nonnegative integers")
        if not isinstance(self.origin_last_requested_at, dict) or not isinstance(self.origin_min_interval, dict):
            raise ValueError("origin timestamps and intervals must be objects")
        for origin, timestamp in {**self.origin_last_requested_at, **self.origin_min_interval}.items():
            target = validate_public_url(origin)
            if (
                target.origin != origin
                or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)
                or timestamp < 0
            ):
                raise ValueError("invalid budget origin timestamp")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> ResearchBudget:
        if value is not None and not isinstance(value, dict):
            raise ValueError("budget must be an object")
        return cls(**(value or {}))


@dataclass
class ContentResult:
    requested_url: str
    captured_at: str
    status: str = "blocked"
    final_url: str | None = None
    http_status: int | None = None
    source_title: str | None = None
    content_type: str | None = None
    text: str = ""
    sha256: str | None = None
    text_sha256: str | None = None
    byte_count: int = 0
    retrieved_by: str = "tradecase.public-http"
    untrusted: bool = True
    assertion_status: str = "unverified"
    is_synthetic: bool = False
    redirects: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    robots: list[dict] = field(default_factory=list)
    hash_basis: str = "raw HTTP response bytes"
    raw_bytes: bytes = field(default=b"", repr=False)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["raw_bytes_base64"] = base64.b64encode(result.pop("raw_bytes")).decode("ascii")
        return result


@dataclass(frozen=True)
class HTTPResponseData:
    status: int
    headers: dict[str, str]
    body: bytes


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("request_deadline_exceeded")
    return value


def _resolve(host: str, port: int, deadline: float) -> list[str]:
    """Bound waiting for getaddrinfo; never consume late resolver results."""
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def lookup():
        try:
            result_queue.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except Exception as exc:
            result_queue.put(exc)

    threading.Thread(target=lookup, daemon=True, name="tradecase-public-dns").start()
    try:
        answer = result_queue.get(timeout=_remaining(deadline))
    except queue.Empty as exc:
        raise TimeoutError("dns_deadline_exceeded") from exc
    if isinstance(answer, Exception):
        raise answer
    return list(dict.fromkeys(item[4][0] for item in answer))


def _connect_pinned(target: PublicURL, ip: str, timeout: float) -> socket.socket:
    """Connect literal IP without another DNS lookup; validate TLS for original host."""
    _public_ip(ip)
    sock = socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
    started = time.monotonic()
    try:
        sock.settimeout(timeout)
        sock.connect((ip, target.port))
        if ipaddress.ip_address(sock.getpeername()[0]) != ipaddress.ip_address(ip):
            raise ReaderPolicyError("connected_peer_mismatch")
        if target.scheme == "https":
            context = ssl.create_default_context()
            # Do not accept user/ambient overrides that disable verification.
            if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
                raise ReaderPolicyError("tls_verification_required")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("tls_deadline_exceeded")
            sock.settimeout(remaining)
            sock = context.wrap_socket(sock, server_hostname=target.host)
        return sock
    except BaseException:
        sock.close()
        raise


def _http_transport(
    target: PublicURL, addresses: tuple[str, ...], policy: ReadPolicy, deadline: float
) -> HTTPResponseData:
    # No retry/fallback loop: one resolved, vetted address per actual request.
    sock = _connect_pinned(target, addresses[0], _remaining(deadline))
    try:
        remaining = _remaining(deadline)
    except TimeoutError:
        sock.close()
        raise
    connection = http.client.HTTPConnection(target.host, target.port, timeout=remaining)
    connection.sock = sock

    def abort():
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    # A watchdog enforces total request time even for slowly dripped headers/body.
    timer = threading.Timer(remaining, abort)
    timer.daemon = True
    timer.start()
    try:
        connection.request(
            "GET",
            target.request_target,
            headers={
                "Host": f"[{target.host}]" if ":" in target.host else target.host,
                "User-Agent": policy.user_agent,
                "Accept": "text/html,text/plain,application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        header_pairs = response.getheaders()
        headers = {key.lower(): value for key, value in header_pairs}
        lengths = [value for key, value in header_pairs if key.lower() == "content-length"]
        if len(lengths) > 1 or (lengths and "transfer-encoding" in headers):
            raise ReaderPolicyError("ambiguous_response_length")
        if headers.get("transfer-encoding", "").lower() not in {"", "chunked"}:
            raise ReaderPolicyError("unsupported_transfer_encoding")
        if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
            raise ReaderPolicyError("compressed_response_rejected")
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) < 0 or int(length) > policy.max_bytes:
                    raise ReaderPolicyError("response_too_large")
            except ValueError as exc:
                if isinstance(exc, ReaderPolicyError):
                    raise
                raise ReaderPolicyError("invalid_content_length") from exc
        chunks: list[bytes] = []
        size = 0
        while True:
            sock.settimeout(_remaining(deadline))
            chunk = response.read1(min(65536, policy.max_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > policy.max_bytes:
                raise ReaderPolicyError("response_too_large")
            chunks.append(chunk)
        if response.length not in (None, 0):
            raise ReaderPolicyError("incomplete_response")
        _remaining(deadline)
        return HTTPResponseData(response.status, headers, b"".join(chunks))
    finally:
        timer.cancel()
        connection.close()
        sock.close()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.skipping = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template", "noscript"}:
            self.skipping += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template", "noscript"}:
            self.skipping = max(0, self.skipping - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.skipping and data.strip():
            text = " ".join(data.split())
            self.parts.append(text)
            if self.in_title:
                self.title.append(text)


def _decode(body: bytes, content_type: str) -> str:
    match = re.search(r'charset\s*=\s*["\']?([A-Za-z0-9._-]+)', content_type, re.I)
    encoding = match.group(1) if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


class ContentReader:
    """One serial, bounded research session. Persist budget in the Case between calls.

    Underscored injection points exist for offline tests; injected transport output
    is always explicitly synthetic and cannot become a live-validation claim.
    """

    def __init__(
        self,
        policy: ReadPolicy | None = None,
        budget: ResearchBudget | None = None,
        *,
        _resolver: Callable | None = None,
        _transport: Callable | None = None,
        _wall_time: Callable = time.time,
        _sleep: Callable = time.sleep,
    ):
        self.policy = policy or ReadPolicy()
        self.budget = budget or ResearchBudget()
        self._resolver = _resolver or _resolve
        self._transport = _transport or _http_transport
        self._synthetic = _resolver is not None or _transport is not None
        self._wall_time, self._sleep = _wall_time, _sleep
        self._robots: dict[str, tuple[RobotFileParser | None, float, dict]] = {}

    def _request(self, target: PublicURL, deadline: float, delay: float = 0) -> HTTPResponseData:
        if self.budget.requests_used >= self.policy.max_requests:
            raise ReaderPolicyError("request_budget_exhausted")
        addresses = self._resolver(target.host, target.port, deadline)
        if not addresses:
            raise ReaderPolicyError("dns_no_results")
        addresses = tuple(dict.fromkeys(_public_ip(ip) for ip in addresses))
        gap = max(self.policy.per_site_interval, delay, self.budget.origin_min_interval.get(target.origin, 0))
        last = self.budget.origin_last_requested_at.get(target.origin)
        if last is not None:
            wait = last + gap - self._wall_time()
            if wait > 0:
                if wait >= _remaining(deadline):
                    raise ReaderPolicyError("spacing_exceeds_deadline")
                self._sleep(wait)
        _remaining(deadline)
        self.budget.requests_used += 1
        self.budget.origin_last_requested_at[target.origin] = self._wall_time()
        response = self._transport(target, addresses, self.policy, deadline)
        _remaining(deadline)
        if len(response.body) > self.policy.max_bytes:
            raise ReaderPolicyError("response_too_large")
        if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
            raise ReaderPolicyError("compressed_response_rejected")
        return response

    def _follow(
        self, url: str, deadline: float, result: ContentResult, *, robots: bool = False
    ) -> tuple[PublicURL, HTTPResponseData]:
        seen: set[str] = set()
        for hop in range(self.policy.max_redirects + 1):
            target = validate_public_url(url)
            if target.url in seen:
                raise ReaderPolicyError("redirect_loop")
            seen.add(target.url)
            delay = 0 if robots else self._check_robots(target, deadline, result)
            response = self._request(target, deadline, delay)
            if response.status not in {301, 302, 303, 307, 308}:
                return target, response
            location = response.headers.get("location")
            if not location:
                raise ReaderPolicyError("redirect_without_location")
            next_target = validate_public_url(urljoin(target.url, location))
            if target.scheme == "https" and next_target.scheme != "https":
                raise ReaderPolicyError("https_downgrade")
            if hop == self.policy.max_redirects:
                raise ReaderPolicyError("redirect_limit")
            if not robots:
                result.redirects.append(next_target.url)
            url = next_target.url
        raise ReaderPolicyError("redirect_limit")

    def _check_robots(self, target: PublicURL, deadline: float, result: ContentResult) -> float:
        if target.origin not in self._robots:
            final, response = self._follow(target.origin + "/robots.txt", deadline, result, robots=True)
            metadata = {
                "requested_url": target.origin + "/robots.txt",
                "final_url": final.url,
                "captured_at": utc_now(),
                "http_status": response.status,
                "sha256": hashlib.sha256(response.body).hexdigest(),
            }
            parser = None
            delay = 0.0
            if response.status in {404, 410}:
                result.warnings.append("robots_absent")
            elif response.status == 200:
                robots_text = _decode(response.body, response.headers.get("content-type", "text/plain"))
                if "<html" in robots_text.lower() or ("user-agent:" not in robots_text.lower() and robots_text.strip()):
                    raise ReaderPolicyError("robots_invalid")
                if any(
                    re.search(r"[*$]", value)
                    for value in re.findall(r"^\s*disallow\s*:\s*([^#\r\n]*)", robots_text, re.I | re.M)
                ):
                    raise ReaderPolicyError("unsupported_robots_pattern")
                parser = RobotFileParser()
                parser.parse(robots_text.splitlines())
                # Honor decimal crawl delays too (stdlib only recognizes integers).
                for value in re.findall(r"^\s*crawl-delay\s*:\s*([^#\s]+)", robots_text, re.I | re.M):
                    try:
                        candidate = float(value)
                    except ValueError as exc:
                        raise ReaderPolicyError("robots_invalid_delay") from exc
                    if not math.isfinite(candidate) or candidate < 0:
                        raise ReaderPolicyError("robots_invalid_delay")
                    delay = max(delay, candidate)
                rate = parser.request_rate(self.policy.user_agent)
                if rate:
                    if rate.requests <= 0 or rate.seconds <= 0:
                        raise ReaderPolicyError("robots_invalid_rate")
                    delay = max(delay, rate.seconds / rate.requests)
            else:
                result.robots.append(metadata)
                raise ReaderPolicyError("robots_unavailable")
            self.budget.origin_min_interval[target.origin] = max(
                delay, self.budget.origin_min_interval.get(target.origin, 0)
            )
            self._robots[target.origin] = (parser, delay, metadata)
        parser, delay, metadata = self._robots[target.origin]
        if metadata not in result.robots:
            result.robots.append(metadata)
        if parser and not parser.can_fetch(self.policy.user_agent, target.url):
            raise ReaderPolicyError("robots_disallow")
        return delay

    def read(self, url: str) -> ContentResult:
        result = ContentResult(requested_url="[rejected-url]", captured_at=utc_now(), is_synthetic=self._synthetic)
        if self._synthetic:
            result.retrieved_by += ".offline-test-double"
        try:
            if self.budget.pages_used >= self.policy.max_pages:
                raise ReaderPolicyError("page_budget_exhausted")
            self.budget.pages_used += 1
            target = validate_public_url(url)
            result.requested_url = target.url
            deadline = time.monotonic() + self.policy.timeout_seconds
            final, response = self._follow(target.url, deadline, result)
            result.final_url, result.http_status = final.url, response.status
            if response.status != 200:
                raise ReaderPolicyError(f"http_status_{response.status}")
            content_type = response.headers.get("content-type", "").lower()
            media_type = content_type.split(";", 1)[0].strip()
            if media_type not in {"text/html", "application/xhtml+xml", "text/plain", "application/json"}:
                raise ReaderPolicyError("unsupported_content_type")
            decoded = _decode(response.body, content_type)
            if media_type in {"text/html", "application/xhtml+xml"}:
                parser = _Text()
                parser.feed(decoded)
                text = "\n".join(parser.parts)
                result.source_title = " ".join(parser.title) or None
            else:
                text = decoded
            if not text.strip():
                raise ReaderPolicyError("empty_content")
            result.status, result.text = "fetched", text
            result.content_type, result.raw_bytes = content_type, response.body
            result.byte_count = len(response.body)
            result.sha256 = hashlib.sha256(response.body).hexdigest()
            result.text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if any(
                marker in text.lower()
                for marker in ("enable javascript", "verify you are human", "access denied", "sign in to continue")
            ):
                result.warnings.append("possible_shell_or_access_challenge")
        except ReaderPolicyError as exc:
            result.status = "blocked"
            result.blockers.append(str(exc))
        except (OSError, TimeoutError, http.client.HTTPException, UnicodeError) as exc:
            result.status = "failed"
            # Exceptions may echo credentials or request data; only type is persisted.
            result.blockers.append("transport_" + type(exc).__name__)
        finally:
            result.captured_at = utc_now()
            result.budget = self.budget.to_dict()
        return result


def normalize_host_search(rows: list[dict], *, query: str, captured_at: str) -> list[dict]:
    """Import host search output, reusing the audited upstream normalizer."""
    utc_timestamp(captured_at)
    if not isinstance(query, str) or len(query) > 4096 or not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("bounded query and at most 100 search rows required")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("search rows must be objects")
    output = []
    for row in normalize_search(rows):
        if row.get("link"):
            row["link"] = validate_public_url(row["link"]).url
        row["url"] = row.get("link", "")
        row["provider_captured_at"] = row["raw"].get("captured_at")
        row.update(
            query=query,
            captured_at=captured_at,
            source_type="search_snippet",
            assertion_status="unverified",
            untrusted=True,
            retrieved_by="host-search-import",
        )
        output.append(row)
    return output


def import_jina_response(
    *,
    source_url: str,
    response_text: str,
    captured_at: str,
    response_url: str,
    http_status: int,
    consent_public_url: bool = False,
) -> ContentResult:
    """Explicitly import a response already read by the host; this performs no I/O.

    No claim of independent origin retrieval, original HTML or remote DNS/redirect
    validation is possible from imported text. Supplied capture time is preserved.
    """
    if consent_public_url is not True:
        raise ReaderPolicyError("explicit_public_url_consent_required")
    utc_timestamp(captured_at)
    source = validate_public_url(source_url)
    relay = urlsplit(response_url)
    if relay.scheme != "https" or relay.netloc != "r.jina.ai" or relay.query or relay.fragment:
        raise ReaderPolicyError("invalid_jina_response_url")
    # Standard Jina endpoint embeds the target URL in its path; verify identity.
    embedded = validate_public_url(relay.path.lstrip("/"))
    if embedded.url != source.url:
        raise ReaderPolicyError("jina_target_mismatch")
    if not isinstance(response_text, str) or len(response_text.encode("utf-8")) > 1_048_576:
        raise ReaderPolicyError("response_too_large")
    result = ContentResult(
        requested_url=source.url,
        final_url=source.url,
        captured_at=captured_at,
        http_status=http_status,
        retrieved_by="host-import:jina",
        hash_basis="imported UTF-8 response text; not original server HTML bytes",
        warnings=[
            "remote_target_chain_unverified",
            "source_dns_not_verified",
            "imported_response_not_independently_retrieved",
        ],
    )
    if type(http_status) is not int or http_status != 200 or not response_text.strip():
        result.status = "failed"
        result.blockers.append("jina_response_not_successful")
        return result
    result.status, result.text = "fetched", response_text
    result.raw_bytes = response_text.encode("utf-8")
    result.sha256 = result.text_sha256 = hashlib.sha256(result.raw_bytes).hexdigest()
    result.byte_count, result.content_type = len(result.raw_bytes), "text/plain; charset=utf-8"
    return result


def optional_provider_status() -> dict:
    """Declare optional boundaries, without imports, probes or user-profile access."""
    return {
        "crawl4ai": {
            "status": "blocked",
            "reason": "optional dependency runtime and current transitive licenses not validated",
            "audited_sha": "888299fb5f0b82181897dc0e61bfb4b036f0aea5",
        },
        "web_access": {
            "status": "blocked",
            "reason": "upstream full license absent; no browser/site authorization or runtime validation",
            "audited_sha": "d173a75978ceb2c63fa0b27f7408cd2bf7fe4310",
        },
        "jina": {"status": "implemented", "mode": "explicit host-response import only; no relay network client"},
    }
