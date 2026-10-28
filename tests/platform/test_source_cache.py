import asyncio
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import update
from test_api import api as api

from tradecase.platform.db import utcnow
from tradecase.platform.source_cache import SourceCache, SourceCacheService


def test_cross_case_source_dedupe_ttl_and_tenant_scope(api):
    _, app, *_ = api
    cache = SourceCacheService(app.state.service, ttl_seconds=60)
    calls = []

    async def fetcher(arguments, request):
        calls.append(request.tenant_id)
        await asyncio.sleep(0.1)
        return {"status": "fetched", "sources": []}

    request = SimpleNamespace(
        tenant_id="alpha", allowed_domains=["public.org"], budget=SimpleNamespace(max_tool_seconds=2)
    )

    async def scenario():
        result = await asyncio.gather(*(cache.fetch({"url": "https://public.org"}, request, fetcher) for _ in range(3)))
        assert len(calls) == 1 and sum(not x["cache_hit"] for x in result) == 1
        request.tenant_id = "beta"
        await cache.fetch({"url": "https://public.org"}, request, fetcher)
        assert len(calls) == 2
        request.tenant_id = "alpha"
        with app.state.service.db.session() as s:
            s.execute(update(SourceCache).values(expires_at=utcnow() - timedelta(seconds=1)))
        await cache.fetch({"url": "https://public.org"}, request, fetcher)
        assert len(calls) == 3

    asyncio.run(scenario())
