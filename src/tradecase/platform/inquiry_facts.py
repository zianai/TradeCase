"""Conservative extraction of explicit inquiry spans; no inferred commercial commitments."""

from __future__ import annotations

import re


def inquiry_facts(inquiry):
    text = inquiry["buyer_message"]
    facts = {}
    for name, field in [
        ("company", "buyer_company_hint"),
        ("email", "buyer_email"),
        ("country", "target_country"),
        ("product", "product_summary"),
        ("website", "buyer_website_hint"),
    ]:
        value = inquiry.get(field)
        if value:
            offset = text.find(value)
            facts[name] = {
                "value": value,
                "source": "inquiry." + field,
                "classification": "USER_PROVIDED",
                "span": {"start": offset, "end": offset + len(value)} if offset >= 0 else None,
            }
    patterns = {
        "quantity": r"\b\d[\d,]*(?:\.\d+)?\s*(?:units?|pcs|pieces?|sets?|kg|tons?|tonnes?)\b",
        "trade_terms": r"\b(?:EXW|FCA|FOB|CFR|CIF|CIP|DAP|DPU|DDP)\b",
        "delivery_request": r"\b(?:deliver(?:y)?(?:\s+by)?|lead\s*time|ship(?:ping)?\s+by)\b[^\n.!?]{0,120}",
        "payment_request": r"\b(?:payment|deposit|letter\s+of\s+credit|L/C|T/T)\b[^\n.!?]{0,120}",
    }
    for name, pattern in patterns.items():
        matches = list(re.finditer(pattern, text, re.I))
        if matches:
            facts[name] = {
                "values": [m.group(0) for m in matches[:10]],
                "source": "inquiry.buyer_message",
                "classification": "USER_REQUEST",
                "spans": [{"start": m.start(), "end": m.end()} for m in matches[:10]],
                "ambiguous": len(matches) > 1,
            }
    expected = {
        "company",
        "email",
        "country",
        "product",
        "quantity",
        "delivery_request",
        "trade_terms",
        "payment_request",
    }
    return {
        "fields": facts,
        "missing_fields": sorted(expected - set(facts)),
        "limitations": "Explicit text spans and supplied fields only; requests are not seller commitments or verified buyer facts.",
    }
