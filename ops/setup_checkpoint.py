"""Explicit checkpoint migrations, executed once before API/worker startup."""

import asyncio

from tradecase.platform.config import Settings
from tradecase.platform.workflow import checkpoint_saver


async def main():
    async with checkpoint_saver(Settings().checkpoint_url, setup=True):
        pass


if __name__ == "__main__":
    asyncio.run(main())
