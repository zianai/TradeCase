"""Offline contracts for the real upstream adapters and the V1 send boundary."""
from __future__ import annotations

import copy
import importlib
import subprocess
import sys
from pathlib import Path

import pytest


def wrapper():
    return importlib.import_module('tradecase.upstream')


def test_public_contacts_are_observed_but_never_verified_or_sendable():
    data = wrapper().extract_contacts(
        'Sales: sales@acme.invalid; Jane: jane@acme.invalid. Call +49 30 12345678.',
        'https://acme.invalid/about',
    )
    assert len(data['emails']) == 2
    assert {x['email'] for x in data['emails']} == {'sales@acme.invalid', 'jane@acme.invalid'}
    assert all(x['source_class'] == 'public' and x['verified'] is False and x['send_allowed'] is False
               for x in data['emails'])
    assert all(x['verification'] == 'format_only' for x in data['emails'])
    assert all(x['source_url'] == 'https://acme.invalid/about' for x in data['emails'])
    assert data['phones'] == ['+49 30 12345678']


def test_contact_pages_only_http_and_same_host():
    text = ('<a href="ftp://acme.invalid/contact">x</a>'
            '<a href="https://evil.invalid/contact">x</a>'
            '<a href="/contact">Contact</a>')
    assert wrapper().extract_contacts(text, 'https://acme.invalid')['contact_pages'] == ['https://acme.invalid/contact']


def test_contacts_do_not_infer_email_from_names():
    assert wrapper().extract_contacts('Please contact Jane Doe.', 'https://acme.invalid')['emails'] == []


def test_search_normalization_calls_real_upstream(monkeypatch):
    upstream = importlib.import_module('tradecase_upstream.normalize_search_results')
    real = upstream.normalize
    calls = []
    def tracked(row, *args, **kwargs):
        calls.append(row)
        return real(row, *args, **kwargs)
    monkeypatch.setattr(upstream, 'normalize', tracked)
    source = {'url': 'https://acme.invalid', 'name': 'Acme', 'description': 'Supplier', 'query': 'acme'}
    result = wrapper().normalize_search([source])[0]
    assert calls == [source]
    assert result['link'] == source['url'] and result['snippet'] == 'Supplier'
    assert result['source_query'] == 'acme' and result['raw'] == source
    assert result['source'] == 'host_import'


def test_dedupe_never_merges_name_only_or_different_candidate_ids():
    rows = [{'company_name': 'Acme', 'country': 'US'}, {'company_name': 'Acme', 'country': 'US'},
            {'candidate_id': 'a', 'website': 'https://acme.invalid'},
            {'candidate_id': 'b', 'website': 'https://acme.invalid'}]
    assert wrapper().dedupe_candidates(rows) == rows


def test_dedupe_merges_same_candidate_without_mutation(monkeypatch):
    upstream = importlib.import_module('tradecase_upstream.dedupe_leads')
    real = upstream.merge
    calls = []
    def tracked(a, b):
        calls.append((a, b))
        return real(a, b)
    monkeypatch.setattr(upstream, 'merge', tracked)
    rows = [{'candidate_id': 'a', 'country': 'US', 'website': 'https://acme.invalid', 'evidence_ids': ['e1']},
            {'candidate_id': 'a', 'country': 'us', 'website': 'https://www.acme.invalid/contact',
             'evidence_ids': ['e2']}]
    before = copy.deepcopy(rows)
    out = wrapper().dedupe_candidates(rows)
    assert len(calls) == 1 and len(out) == 1
    assert out[0]['evidence_ids'] == ['e1', 'e2']
    assert rows == before


@pytest.mark.parametrize('other', [{'country': 'DE'}, {'website': 'https://other.invalid'},
                                   {'domain': 'other.invalid'}])
def test_same_candidate_id_conflicts_are_not_silently_merged(other):
    base = {'candidate_id': 'a', 'country': 'US', 'website': 'https://acme.invalid'}
    rows = [base, {'candidate_id': 'a', **other}]
    assert wrapper().dedupe_candidates(rows) == rows


def test_customs_remains_tentative_without_priority_points(monkeypatch):
    upstream = importlib.import_module('tradecase_upstream.customs_verify')
    real = upstream.analyze
    calls = []
    def tracked(company, rows):
        calls.append(company)
        return real(company, rows)
    monkeypatch.setattr(upstream, 'analyze', tracked)
    result = wrapper().customs_signals('Acme', [{
        'title': 'Acme shipments', 'link': 'https://importyeti.com/company/acme',
        'snippet': 'Acme has 200 shipments from Ningbo China. HS code 123456. 2026-01-01.'}])
    assert calls == ['Acme'] and result['evidence']
    assert result['assertion_status'] == 'unverified' and result['tentative'] is True
    assert result['confirmed_import_activity'] is False
    assert result['confirmed_asia_import_signal'] is False
    assert result['fit_score_adjustment'] == 0
    assert all(x['assertion_status'] == 'unverified' for x in result['evidence'])


def test_hash_and_claim_risk_are_real_upstream_exports():
    upstream = importlib.import_module('tradecase_upstream.evaluate_outreach_drafts')
    assert wrapper().body_hash is upstream.body_hash
    assert wrapper().claim_risk is upstream.claim_risk
    original = {'recipient_email': 'SALES@acme.invalid', 'subject': 'Inquiry', 'body_text': 'Hello'}
    assert wrapper().body_hash(original) == wrapper().body_hash({**original, 'recipient_email': 'sales@acme.invalid'})
    assert wrapper().body_hash(original) != wrapper().body_hash({**original, 'body_text': 'Changed'})
    review, block, actions = [], [], []
    score = wrapper().claim_risk({'body_text': 'We are certified.', 'claims_made': [{'risk': 'high'}]},
                                 review, block, actions)
    assert score < 1 and block and review and actions


def test_send_function_is_disabled_before_any_credentials_or_network(monkeypatch):
    sender = importlib.import_module('tradecase_upstream.send_smtp')
    class DoNotRead(dict):
        def get(self, *args, **kwargs):
            pytest.fail('Disabled send must not read config or credential references')
        def __getitem__(self, key):
            pytest.fail('Disabled send must not read config')
    with pytest.raises(RuntimeError, match='disabled in TradeCase V1'):
        sender.send_message(None, DoNotRead())


def test_send_main_is_disabled_before_reading_files(monkeypatch, capsys):
    sender = importlib.import_module('tradecase_upstream.send_smtp')
    def forbidden(*args, **kwargs):
        pytest.fail('Disabled entrypoint must not open drafts or SMTP configuration')
    monkeypatch.setattr(sender, 'read_jsonl', forbidden)
    monkeypatch.setattr(sender, 'read_json', forbidden)
    monkeypatch.setattr(sys, 'argv', ['send_smtp.py', '--drafts', 'not-read.jsonl', '--send-approved'])
    assert sender.main() != 0
    assert 'disabled in TradeCase V1' in capsys.readouterr().err


def test_send_script_is_disabled_even_with_send_flag():
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run([sys.executable, str(root / 'scripts/send_smtp.py'),
                           '--drafts', 'does-not-exist.jsonl', '--send-approved'],
                          cwd=root, capture_output=True, text=True, timeout=5)
    assert proc.returncode != 0 and 'disabled in TradeCase V1' in proc.stderr
