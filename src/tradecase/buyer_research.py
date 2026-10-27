"""Offline buyer research preparation, with no automatic entity verification.

Host Agents resolve identities and interpret source claims. This module only
turns explicit input hints and already obtained page text into reviewable Case
records. It does not search, fetch, infer a private email, or choose a buyer.
"""
from __future__ import annotations

import hashlib
from itertools import combinations

from tradecase_upstream.extract_contacts import FREE_MAIL_DOMAINS, domain_relation

from tradecase.models import BuyerProfile, Candidate, CaseInput, Contact, Evidence
from tradecase.upstream import extract_contacts
from tradecase.vendor.ai_hunter.url_filter import _bare_domain, classify_url


def _candidate_id(case_id: str, kind: str, value: str) -> str:
    seed = f'{case_id}|{kind}|{value}'.encode('utf-8')
    return 'candidate-' + hashlib.sha256(seed).hexdigest()[:20]


def _email_domain(inquiry: CaseInput) -> str | None:
    if not inquiry.buyer_email:
        return None
    domain = _bare_domain('https://' + inquiry.buyer_email.rsplit('@', 1)[1])
    if not domain or domain in FREE_MAIL_DOMAINS:
        return None
    return domain


def prepare_candidates(input_dict: dict, evidence_rows: list[dict] | None = None) -> list[dict]:
    """Create stable unverified candidates from user hints, never from a name join.

    Evidence is accepted for API consistency but cannot silently certify input
    hints. Host-authored candidate evidence bindings are a separate review step.
    """
    inquiry = CaseInput.model_validate(input_dict)
    for row in evidence_rows or []:
        Evidence.model_validate(row)
    hint = (inquiry.buyer_company_hint or '').strip() or None
    website = inquiry.buyer_website_hint
    website = website if website and classify_url(website) == 'company_site' else None
    website_domain = _bare_domain(website) if website else None
    email_domain = _email_domain(inquiry)
    candidates = []
    if website_domain:
        candidates.append(Candidate(
            candidate_id=_candidate_id(inquiry.case_id, 'domain', website_domain),
            name=hint or website_domain, website=website, domain=website_domain,
            is_synthetic=inquiry.is_synthetic,
        ))
    if email_domain and email_domain != website_domain:
        candidates.append(Candidate(
            candidate_id=_candidate_id(inquiry.case_id, 'domain', email_domain),
            name=hint or email_domain, domain=email_domain, is_synthetic=inquiry.is_synthetic,
        ))
    if not candidates and hint:
        candidates.append(Candidate(
            candidate_id=_candidate_id(inquiry.case_id, 'name_hint', hint.casefold()),
            name=hint, is_synthetic=inquiry.is_synthetic,
        ))
    return [row.model_dump() for row in candidates]


def summarize_conflicts(candidates: list[dict]) -> list[str]:
    """Report ambiguity without merging or resolving any entity record."""
    rows = [Candidate.model_validate(row) for row in candidates]
    issues = []
    if len(rows) > 1:
        issues.append('multiple_candidates: entity identity remains unresolved')
    for a, b in combinations(rows, 2):
        same_name = a.name.strip().casefold() == b.name.strip().casefold()
        same_id = a.candidate_id == b.candidate_id
        same_domain = bool(a.domain and b.domain and a.domain.casefold() == b.domain.casefold())
        same_registry = bool(a.registry_id and b.registry_id and a.registry_id == b.registry_id)
        pair = f'{a.candidate_id}, {b.candidate_id}'
        if same_name and not same_id:
            issues.append(f'same_name_multiple_candidates: {pair}; same name is not identity evidence')
        if same_name or same_id or same_domain or same_registry:
            for key in ('name', 'domain', 'country', 'registry_id'):
                first, second = getattr(a, key), getattr(b, key)
                if first and second and str(first).casefold() != str(second).casefold():
                    issues.append(f'{key}_conflict: {pair}; retain both observations for review')
    return list(dict.fromkeys(issues))


def research_from_local(input_dict: dict, evidence_rows: list[dict], page_texts: list[dict] | None = None) -> dict:
    """Return candidates, a profile, and page observations without any I/O.

    ``page_texts`` rows contain ``source_url``, ``text`` and optional
    ``evidence_ids``. Referenced evidence must exist and match that URL. Outputs
    with no evidence remain visibly unresolved. Observations are supplementary
    data for the host, not Evidence records or facts to copy into a final report.
    """
    inquiry = CaseInput.model_validate(input_dict)
    evidence = [Evidence.model_validate(row) for row in evidence_rows]
    index = {row.evidence_id: row for row in evidence}
    if len(index) != len(evidence):
        raise ValueError('duplicate evidence_id in evidence_rows')
    candidates = prepare_candidates(input_dict, evidence_rows)
    unresolved = [
        'company_name and domain are user-provided hints; verify the legal entity and website ownership',
        'buyer_role is unknown; require source evidence of purchasing or distribution activity',
        'inquiry_relationship is unverified; link the sender to the chosen legal entity',
        'country is unknown; destination country does not establish buyer residence',
    ]
    unresolved.extend(summarize_conflicts(candidates))
    if not candidates:
        unresolved.append('No company candidate can be derived from the available hints')
    website = inquiry.buyer_website_hint
    website = website if website and classify_url(website) == 'company_site' else None
    if inquiry.buyer_website_hint:
        unresolved.append('website is an unverified user hint; URL classification does not establish ownership')
    if inquiry.buyer_website_hint and not website:
        unresolved.append('website hint is a platform/content page or invalid public URL, not a company website')
    if inquiry.buyer_email and inquiry.buyer_email.rsplit('@', 1)[1].lower() in FREE_MAIL_DOMAINS:
        unresolved.append('free_mail address: do not derive a company or company website from the mailbox domain')
    domains = {row['domain'] for row in candidates if row['domain']}
    if len(domains) > 1:
        unresolved.append('domain mismatch between website and inquiry email; entity identity needs review')
    contacts = []
    if inquiry.buyer_email:
        contacts.append(Contact(
            email=inquiry.buyer_email.lower(), source_class='user_provided',
            domain_relation=domain_relation(inquiry.buyer_email, website or ''),
        ).model_dump())
        unresolved.append('contacts: the inquiry sender is user-provided, not a verified public contact')
    observations = []
    for page in page_texts or []:
        if not isinstance(page, dict) or not isinstance(page.get('text'), str):
            raise ValueError('page_texts entries require source_url and text strings')
        url = page.get('source_url')
        category = classify_url(url)
        if category == 'irrelevant':
            raise ValueError('page source_url must be a valid public HTTP(S) content URL')
        ids = page.get('evidence_ids', [])
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise ValueError('page evidence_ids must be a list of strings')
        for evidence_id in ids:
            if evidence_id not in index:
                raise ValueError(f'unknown page evidence_id: {evidence_id}')
            if index[evidence_id].source_url != url:
                raise ValueError(f'page source_url differs from evidence {evidence_id}')
        extracted = extract_contacts(page['text'], url)
        observations.append({
            'source_url': url, 'source_category': category, 'evidence_ids': list(ids),
            'assertion_status': 'unverified', 'extracted': extracted,
            'is_synthetic': inquiry.is_synthetic or any(index[item].is_synthetic for item in ids),
        })
        if not ids:
            unresolved.append(f'contacts: page {url} needs captured source evidence before use')
        if _bare_domain(url) not in domains:
            unresolved.append(f'contacts: page {url} is not bound to a candidate domain; observations retained separately')
            continue
        for item in extracted['emails']:
            contact = Contact(
                email=item['email'], source_class='public', source_url=url,
                evidence_ids=list(ids), domain_relation=item['domain_relation'],
            ).model_dump()
            if contact not in contacts:
                contacts.append(contact)
    profile = BuyerProfile(
        case_id=inquiry.case_id,
        candidate_ids=[row['candidate_id'] for row in candidates],
        company_name=(inquiry.buyer_company_hint or '').strip() or None,
        website=website, domain=next(iter(domains)) if len(domains) == 1 else None,
        contacts=contacts, unresolved_items=list(dict.fromkeys(unresolved)),
        is_synthetic=inquiry.is_synthetic,
    )
    return {'candidates': candidates, 'profile': profile.model_dump(), 'observations': observations}
