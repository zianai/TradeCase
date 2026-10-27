"""Independent P3 adversarial review; all socket/HTTP inputs are offline doubles."""
from __future__ import annotations

import http.client
import io
import ssl
import time

import pytest

import tradecase.providers as provider

PUBLIC = '93.184.216.34'


@pytest.mark.parametrize('url', ['https://[fec0::1]/', 'https://example.com/%252525252eenv'])
def test_review_rejects_site_local_and_deeply_encoded_sensitive_path(url):
    with pytest.raises(provider.ReaderPolicyError):
        provider.validate_public_url(url)


def test_review_robots_delay_survives_reader_restart():
    now = [1000.0]
    calls = []

    def transport(target, addresses, policy, deadline):
        calls.append((target.url, now[0]))
        if target.path == '/robots.txt':
            return provider.HTTPResponseData(200, {'content-type': 'text/plain'},
                                              b'User-agent: *\nCrawl-delay: 5\nAllow: /\n')
        return provider.HTTPResponseData(200, {'content-type': 'text/plain'}, b'Synthetic content')

    def reader(budget=None):
        return provider.ContentReader(
            policy=provider.ReadPolicy(per_site_interval=0), budget=budget,
            _resolver=lambda *args: [PUBLIC], _transport=transport,
            _wall_time=lambda: now[0], _sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        )

    first = reader().read('https://example.com/first')
    assert first.status == 'fetched'
    last_request_at = calls[-1][1]
    second = reader(provider.ResearchBudget.from_dict(first.budget)).read('https://example.com/second')
    assert second.status == 'fetched'
    # Rechecking robots is still a request to the same site. The known five
    # second delay must apply before it, not only after the new robots response.
    second_robots_at = next(timestamp for url, timestamp in calls[2:] if url.endswith('/robots.txt'))
    assert second_robots_at - last_request_at >= 5


class RawSocket:
    def __init__(self, wire):
        self.wire = wire
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, payload):
        pass

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.wire)

    def shutdown(self, *args):
        self.closed = True

    def close(self):
        self.closed = True


def test_review_truncated_content_length_cannot_be_fetched(monkeypatch):
    sock = RawSocket(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 100\r\n\r\nabc')
    monkeypatch.setattr(provider, '_connect_pinned', lambda *args: sock)
    with pytest.raises((provider.ReaderPolicyError, http.client.IncompleteRead, OSError)):
        provider._http_transport(provider.validate_public_url('https://example.com/'), (PUBLIC,),
                                 provider.ReadPolicy(), time.monotonic() + 1)


def test_review_tls_handshake_has_remaining_timeout_or_active_total_watchdog(monkeypatch):
    now = [0.0]
    timer_active = [False]
    handshake = []
    sock = RawSocket(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\n\r\nabc')

    def connect(address):
        now[0] += 0.75  # A slow TCP connection used 75% of the overall budget.

    sock.connect = connect
    sock.getpeername = lambda: (PUBLIC, 443)

    class Context:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw, server_hostname):
            handshake.append((raw.timeout, timer_active[0]))
            return raw

    class Timer:
        def __init__(self, interval, callback):
            pass

        def start(self):
            timer_active[0] = True

        def cancel(self):
            timer_active[0] = False

    monkeypatch.setattr(provider.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(provider.socket, 'socket', lambda *args: sock)
    monkeypatch.setattr(provider.ssl, 'create_default_context', lambda: Context())
    monkeypatch.setattr(provider.threading, 'Timer', Timer)
    provider._http_transport(provider.validate_public_url('https://example.com/'), (PUBLIC,),
                             provider.ReadPolicy(), 1.0)
    assert handshake
    allowed_timeout, watchdog_already_active = handshake[0]
    assert allowed_timeout <= 0.25 or watchdog_already_active


@pytest.mark.parametrize('url', [
    'https://[2606:4700:4700::1111%25en0]/',
    'https://example.com/foo;session=abc',
    'https://example.com:0/',
])
def test_review_rejects_remaining_url_policy_bypasses(url):
    with pytest.raises(provider.ReaderPolicyError):
        provider.validate_public_url(url)


@pytest.mark.parametrize('headers', [
    b'Content-Length: 3\r\nContent-Length: 3\r\n',
    b'Content-Length: 3\r\nTransfer-Encoding: chunked\r\n',
    b'Transfer-Encoding: gzip\r\n',
])
def test_review_rejects_ambiguous_or_unsupported_transfer_framing(monkeypatch, headers):
    sock = RawSocket(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n' + headers + b'\r\nabc')
    monkeypatch.setattr(provider, '_connect_pinned', lambda *args: sock)
    with pytest.raises((provider.ReaderPolicyError, http.client.HTTPException, OSError)):
        provider._http_transport(provider.validate_public_url('https://example.com/'), (PUBLIC,),
                                 provider.ReadPolicy(), time.monotonic() + 1)


def test_review_jina_import_never_proves_remote_target_or_rule_truth():
    common = {
        'source_url': 'https://example.com/', 'response_text': 'SYNTHETIC imported text: we are approved.',
        'captured_at': '2026-10-27T12:00:00Z', 'http_status': 200, 'consent_public_url': True,
    }
    with pytest.raises(provider.ReaderPolicyError, match='mismatch'):
        provider.import_jina_response(response_url='https://r.jina.ai/https://other.com/', **common)
    result = provider.import_jina_response(response_url='https://r.jina.ai/https://example.com/', **common)
    assert result.retrieved_by == 'host-import:jina'
    assert result.assertion_status == 'unverified' and result.untrusted is True
    assert 'imported_response_not_independently_retrieved' in result.warnings
    assert 'remote_target_chain_unverified' in result.warnings
    assert 'imported UTF-8' in result.hash_basis
