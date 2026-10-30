"""Authenticated local business API; never exposes engine credentials."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from .schemas import ApprovePlan, AssetReview, Attach, PlanInput, ProductInput, Revise, VersionInput


def router(service, actor, idem):
    r = APIRouter()

    @r.get("/api/cases/{cid}/visuals")
    def summary(cid: str, user=Depends(actor)):
        return service.summary_for_case(user["tenant_id"], cid)

    @r.post("/api/cases/{cid}/visuals/suggestions")
    def suggest(cid: str, body: list[dict], user=Depends(actor)):
        if len(body) > 10:
            raise ValueError("Too many semantic candidates")
        return service.suggest(user, cid, body)

    @r.post("/api/cases/{cid}/visuals/products", status_code=201)
    def product(cid: str, body: ProductInput, user=Depends(actor), key=Depends(idem)):
        return service.product(user, cid, body, key)

    @r.post("/api/cases/{cid}/visuals/assets", status_code=201)
    async def upload(
        cid: str,
        file: UploadFile = File(...),
        product_id: str = Form(...),
        source: str = Form(...),
        authorized: bool = Form(False),
        external_use: bool = Form(False),
        kind: str = Form("product"),
        user=Depends(actor),
        key=Depends(idem),
    ):
        raw = await file.read(service.settings.max_asset_bytes + 1)
        return service.upload(user, cid, product_id, raw, source, authorized, external_use, kind, key)

    @r.post("/api/cases/{cid}/visuals/tasks", status_code=201)
    def create(cid: str, body: PlanInput, user=Depends(actor), key=Depends(idem)):
        return service.create(user, cid, body, key)

    @r.get("/api/visual-tasks/{tid}")
    def get(tid: str, user=Depends(actor)):
        return service.get(user, tid)

    @r.post("/api/visual-tasks/{tid}/approve-plan")
    def approve(tid: str, body: ApprovePlan, user=Depends(actor), key=Depends(idem)):
        return service.approve(user, tid, body, key)

    @r.post("/api/visual-tasks/{tid}/sync")
    async def sync(tid: str, body: VersionInput, user=Depends(actor), key=Depends(idem)):
        return await service.sync(user, tid, body.version)

    @r.post("/api/visual-tasks/{tid}/cancel")
    async def cancel(tid: str, body: VersionInput, user=Depends(actor), key=Depends(idem)):
        return await service.cancel(user, tid, body, key)

    @r.post("/api/visual-tasks/{tid}/revisions")
    def revise(tid: str, body: Revise, user=Depends(actor), key=Depends(idem)):
        return service.revise(user, tid, body, key)

    @r.post("/api/visual-tasks/{tid}/reviews")
    def review(tid: str, body: AssetReview, user=Depends(actor), key=Depends(idem)):
        return service.review(user, tid, body, key)

    @r.post("/api/visual-tasks/{tid}/attach")
    def attach(tid: str, body: Attach, user=Depends(actor), key=Depends(idem)):
        return service.attach(user, tid, body, key)

    @r.get("/api/visual-assets/{identity}/content")
    def image(identity: str, user=Depends(actor)):
        raw, mime = service.content(user, identity)
        return Response(
            raw,
            media_type=mime,
            headers={"Content-Disposition": "inline", "Content-Security-Policy": "default-src 'none'"},
        )

    @r.get("/api/visual-source-assets/{identity}/content")
    def reference(identity: str, user=Depends(actor)):
        raw, mime = service.content(user, identity, True)
        return Response(
            raw,
            media_type=mime,
            headers={"Content-Disposition": "inline", "Content-Security-Policy": "default-src 'none'"},
        )

    @r.get("/api/visual-proposals/{identity}/export")
    def export(identity: str, user=Depends(actor)):
        return Response(
            service.export(user, identity),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="visual-proposal.zip"'},
        )

    return r
