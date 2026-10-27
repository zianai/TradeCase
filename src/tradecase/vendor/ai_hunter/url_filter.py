# Adapted from xiongQvQ/AI_Find_Customer, backend/tools/url_filter.py
# Locked commit: 9b2fde8f719623c627516da2663707a893ee6805
# Copyright (c) 2026 AI Hunter. MIT; complete notice in ./LICENSE.
# TradeCase changes: validate HTTP(S), credentials, ports and literal local
# hosts; classify canonical hostname; match LinkedIn only on its own host/path.
# This is a pure classifier, not a DNS/redirect or SSRF security boundary.
"""URL classifier — lightweight categorisation of search result URLs.

Classifies URLs into categories so the LeadExtract pipeline can route them
to the right processing strategy.  Only *truly useless* URLs are marked
``irrelevant`` (search-engine result pages, pure entertainment with zero
B2B signal).  Everything else is kept — articles, blogs, and forums may
contain valuable company mentions that the LLM can extract.

Design principle: **classify, don't discard**.  Let the model decide.
"""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import urlparse

# ── Truly irrelevant domains — zero B2B signal ──────────────────────────
# Only search-engine SERPs and pure entertainment / consumer platforms
# that will *never* yield company leads.
_IRRELEVANT_DOMAINS: set[str] = {
    # Search engines (their own result pages, not useful to scrape)
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "baidu.com",
    # Pure entertainment / consumer — no B2B signal
    "tiktok.com", "twitch.tv", "spotify.com", "netflix.com",
    "pinterest.com", "tumblr.com", "dailymotion.com",
}

# ── B2B platforms — Jina can scrape these, keep as platform_listing ──────
_PLATFORM_DOMAINS: dict[str, str] = {
    "alibaba.com": "alibaba",
    "made-in-china.com": "made_in_china",
    "europages.com": "europages",
    "thomasnet.com": "thomasnet",
    "indiamart.com": "indiamart",
    "kompass.com": "kompass",
    "globalsources.com": "globalsources",
    "tradeindia.com": "tradeindia",
}

# ── LinkedIn company URL pattern ─────────────────────────────────────────
_LINKEDIN_COMPANY_RE = re.compile(
    r"^/company/([a-zA-Z0-9_-]+)(?:/|$)", re.IGNORECASE,
)

# ── Content-rich domains — articles, blogs, directories that may mention
#    companies.  We scrape these and let the LLM extract company names. ───
_CONTENT_DOMAINS: set[str] = {
    # News / media — may have "top 10 suppliers" lists
    "reuters.com", "bloomberg.com", "forbes.com", "techcrunch.com",
    "businessinsider.com", "cnbc.com", "ft.com",
    "bbc.com", "cnn.com", "nytimes.com", "theguardian.com",
    "washingtonpost.com", "wired.com", "zdnet.com", "arstechnica.com",
    "theverge.com",
    # Blogging / content platforms
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
    # Knowledge
    "wikipedia.org", "wikimedia.org",
    # Q&A / forums
    "reddit.com", "quora.com",
    # Social (may have company pages)
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "vimeo.com",
    # Job boards (company info available)
    "indeed.com", "glassdoor.com",
    # B2B directories / data
    "crunchbase.com", "zoominfo.com", "dnb.com", "pitchbook.com",
    "opencorporates.com",
    # E-commerce (some sellers are B2B)
    "amazon.com", "ebay.com",
}


def _bare_domain(url: str) -> str:
    """Return a canonical HTTP(S) hostname or empty for an unsafe URL shape.

    No DNS is resolved. In particular a domain can still resolve to a private
    address, so network callers must use the ContentReader policy separately.
    """
    if not isinstance(url, str) or "\\" in url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return ""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None or parsed.port not in {None, 80, 443}:
            return ""
        domain = parsed.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        return ""
    try:
        literal = ip_address(domain)
    except ValueError:
        if "." not in domain or domain.rsplit(".", 1)[-1].isdigit() or domain.endswith((".localhost", ".local", ".internal")):
            return ""
        if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split(".")):
            return ""
    else:
        if not literal.is_global:
            return ""
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _domain_matches(domain: str, target: str) -> bool:
    return domain == target or domain.endswith("." + target)


def classify_url(url: str) -> str:
    """Classify a URL into a processing category.

    Returns one of:
        - ``"company_site"`` — likely a company's own website → direct scrape
        - ``"platform_listing"`` — B2B platform page → scrape for company info
        - ``"linkedin_company"`` — LinkedIn company page → resolve to official site
        - ``"content_page"`` — article / blog / forum / directory that may
          mention companies → scrape and let LLM extract company names
        - ``"irrelevant"`` — truly useless (search-engine SERP, pure
          entertainment) → skip
    """
    if not url:
        return "irrelevant"

    domain = _bare_domain(url)
    if not domain:
        return "irrelevant"

    # 1. Truly irrelevant
    for d in _IRRELEVANT_DOMAINS:
        if _domain_matches(domain, d):
            return "irrelevant"

    # 2. LinkedIn company pages — special handling (Jina can't scrape)
    if _domain_matches(domain, "linkedin.com") and _LINKEDIN_COMPANY_RE.search(urlparse(url).path):
        return "linkedin_company"

    # 3. LinkedIn non-company pages (profiles, posts) → content
    if _domain_matches(domain, "linkedin.com"):
        return "content_page"

    # 4. B2B platform listings
    for pd in _PLATFORM_DOMAINS:
        if _domain_matches(domain, pd):
            return "platform_listing"

    # 5. Content-rich domains (news, blogs, forums, directories)
    for cd in _CONTENT_DOMAINS:
        if _domain_matches(domain, cd):
            return "content_page"

    # 6. Default — treat as a potential company website
    return "company_site"


def extract_linkedin_company_slug(url: str) -> str | None:
    """Extract company slug from a LinkedIn company URL.

    Example:
        ``"https://ca.linkedin.com/company/itc-electrical-components"``
        → ``"itc-electrical-components"``
    """
    domain = _bare_domain(url)
    if not domain or not _domain_matches(domain, "linkedin.com"):
        return None
    match = _LINKEDIN_COMPANY_RE.search(urlparse(url).path)
    if match:
        return match.group(1)
    return None


def slug_to_company_name(slug: str) -> str:
    """Convert a URL slug to a human-readable company name.

    Example:
        ``"itc-electrical-components"`` → ``"itc electrical components"``
    """
    return slug.replace("-", " ").replace("_", " ").strip()


def classify_search_results(
    results: list[dict],
) -> dict[str, list[dict]]:
    """Classify search results into processing buckets.

    Unlike the old ``filter_search_results``, **nothing is discarded** except
    truly irrelevant URLs.  Articles, blogs, and forums are kept in the
    ``content_page`` bucket for LLM-based company extraction.

    Args:
        results: List of search result dicts with ``"link"`` key.

    Returns:
        Dict mapping category → list of results::

            {
                "company_site": [...],
                "platform_listing": [...],
                "linkedin_company": [...],
                "content_page": [...],
                "irrelevant": [...],
            }
    """
    buckets: dict[str, list[dict]] = {
        "company_site": [],
        "platform_listing": [],
        "linkedin_company": [],
        "content_page": [],
        "irrelevant": [],
    }

    for r in results:
        url = r.get("link", "")
        category = classify_url(url)
        buckets[category].append(r)

    return buckets


# ── Backward-compatible wrapper (used by existing code) ──────────────────

def filter_search_results(
    results: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Backward-compatible wrapper around :func:`classify_search_results`.

    Returns:
        Tuple of (company_sites, platform_listings, linkedin_companies).
        Content pages are merged into company_sites so they get scraped.
        Only truly irrelevant URLs are dropped.
    """
    buckets = classify_search_results(results)
    # Content pages go into company_sites — the LLM will decide their value
    company_sites = buckets["company_site"] + buckets["content_page"]
    return company_sites, buckets["platform_listing"], buckets["linkedin_company"]
