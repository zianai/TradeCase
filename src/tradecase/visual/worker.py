"""Wake existing approved runs; the Engine owns image generation workers."""

import asyncio


async def recover_visual(ctx):
    from .service import VisualService

    visual = ctx.get("visual")
    if visual is None:
        visual = VisualService(ctx["service"])
        ctx["visual"] = visual
    await visual.recover_due()


async def recover_visual_local(service):
    ctx = {"service": service}
    while True:
        try:
            await recover_visual(ctx)
        except Exception:
            # Optional integration failure never interrupts the independent Case worker.
            pass
        await asyncio.sleep(15)
