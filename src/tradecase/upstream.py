"""Conservative adapters over audited B2B Lead Hunter implementations.

The original algorithms stay in ``tradecase_upstream`` (the retained scripts/
folder). These wrappers add Case semantics; they do not fetch, verify identity,
assign priority, or send messages. Extracted contact values remain observations.
"""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlsplit

from tradecase_upstream import customs_verify as _customs
from tradecase_upstream import dedupe_leads as _dedupe
from tradecase_upstream import extract_contacts as _contacts
from tradecase_upstream import normalize_search_results as _search
from tradecase_upstream.evaluate_outreach_drafts import body_hash, claim_risk

__all__ = ['extract_contacts', 'normalize_search', 'dedupe_candidates', 'customs_signals', 'body_hash', 'claim_risk']


def _http_hostname(value: str) -> str:
    """Syntactic link check only; network/DNS policy belongs to ContentReader."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return ''
        if parsed.port not in {None, 80, 443}:
            return ''
        return parsed.hostname.lower()
    except ValueError:
        return ''


def extract_contacts(text: str, source_url: str, company_domain: str = '') -> dict:
    """Extract public-page observations through upstream; never infer or verify."""
    emails = _contacts.extract_emails(text, source_url, company_domain)
    for item in emails:
        item.update(source_class='public', verified=False, send_allowed=False)
    host = _http_hostname(source_url)
    pages = _contacts.discover_contact_pages(text, source_url)
    pages = [url for url in pages if host and _http_hostname(url) == host]
    return {
        'source_url': source_url,
        'emails': emails,
        'phones': _contacts.extract_phones(text),
        'social': _contacts.extract_social(text),
        'contact_pages': pages,
    }


def normalize_search(rows: list[dict]) -> list[dict]:
    """Normalize host-supplied search data without claiming a Hermes retrieval."""
    results = []
    for row in rows:
        normalized = _search.normalize(deepcopy(row))
        if not row.get('source') and not row.get('provider'):
            normalized['source'] = 'host_import'
        results.append(normalized)
    return results


def _domains(row: dict) -> set[str]:
    domains = set()
    for key in ('website', 'domain', 'official_website'):
        value = str(row.get(key) or '').strip()
        if value:
            domain = _dedupe.domain(value if '://' in value else 'https://' + value)
            if domain:
                domains.add(domain)
    return domains


def _conflicts(a: dict, b: dict) -> bool:
    ac = str(a.get('country') or '').strip().casefold()
    bc = str(b.get('country') or '').strip().casefold()
    unknown = {'', 'unknown', 'unverified'}
    if ac not in unknown and bc not in unknown and ac != bc:
        return True
    da, db = _domains(a), _domains(b)
    # Conflicting fields within one candidate are also kept for review.
    return len(da) > 1 or len(db) > 1 or bool(da and db and da != db)


def dedupe_candidates(rows: list[dict]) -> list[dict]:
    """Merge repeated explicit candidate IDs only, preserving ambiguous rows.

    Names, addresses, email domains and website domains do not establish entity
    identity. A country or domain conflict keeps both records for the Case's
    subsequent conflict review. The original merge algorithm is reused only
    after this gate, with copies because upstream merges list values in place.
    """
    result: list[dict] = []
    by_id: dict[str, list[int]] = {}
    for source in rows:
        row = deepcopy(source)
        candidate_id = row.get('candidate_id')
        if candidate_id is not None and not isinstance(candidate_id, str):
            raise ValueError('candidate_id must be a string or null')
        matched = False
        if candidate_id:
            indexes = by_id.get(candidate_id, [])
            # Once a candidate ID has conflicting observations, keep subsequent
            # rows separate too; a partial row cannot silently bridge a conflict.
            if len(indexes) == 1 and not _conflicts(result[indexes[0]], row):
                idx = indexes[0]
                result[idx] = _dedupe.merge(result[idx], row)
                matched = True
        if not matched:
            if candidate_id:
                by_id.setdefault(candidate_id, []).append(len(result))
            result.append(row)
    return result


def customs_signals(company: str, rows: list[dict]) -> dict:
    """Expose upstream extraction as tentative search clues with zero points.

    Upstream's confidence and confirmed flags are heuristics over snippets, not
    verification. Only extracted details are retained; no claim earns priority.
    """
    raw = _customs.analyze(company, normalize_search(rows))
    evidence = []
    for item in raw['evidence']:
        item = deepcopy(item)
        item['upstream_heuristic_confidence'] = item.pop('confidence', None)
        item['source_type'] = 'search_snippet'
        item['assertion_status'] = 'unverified'
        evidence.append(item)
    return {
        'company_name': company,
        'assertion_status': 'unverified',
        'tentative': True,
        'confirmed_import_activity': False,
        'confirmed_asia_import_signal': False,
        'fit_score_adjustment': 0,
        'evidence': evidence,
    }
