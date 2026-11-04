"""Bank statement upload and suggestion review."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.money import format_amount
from app.core.security import check_id, check_invoice_number, spreadsheet_safe
from app.repositories import Repos
from app.routes.deps import rate_limit, repos, require_user, serialize
from app.services import reconciliation as svc

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"], dependencies=[Depends(require_user)])


@router.post("/statements", dependencies=[rate_limit("upload", 10, 60)], status_code=201)
async def upload(request: Request, file: UploadFile = File(...), r: Repos = Depends(repos),
                 user: str = Depends(require_user)) -> dict:
    s = request.app.state.settings
    data = await file.read(s.max_upload_bytes + 1)
    stmt = await svc.upload_statement(r, file.filename or "", file.content_type or "", data, user,
                                      s.max_upload_bytes, s.max_statement_rows)
    return serialize(stmt)


@router.get("/statements")
async def list_statements(r: Repos = Depends(repos)) -> list[dict]:
    return [serialize(s) for s in await r.recon.list_statements()]


def _row_view(row: dict) -> dict:
    t, s = row["transaction"], row["suggestion"]
    tv = serialize(t)
    tv["amount_display"] = format_amount(t["amount_minor"], t["currency"])
    sv = serialize(s) if s else None
    if sv:
        for a in sv.get("allocations", []):
            a["amount_display"] = format_amount(a["amount_minor"], t["currency"])
            if a.get("tds_minor"):
                a["tds_display"] = format_amount(a["tds_minor"], t["currency"])
            if "balance_minor" in a:
                a["balance_display"] = format_amount(a["balance_minor"], t["currency"])
            if a.get("expected_tds_minor"):
                a["expected_tds_display"] = format_amount(a["expected_tds_minor"], t["currency"])
    return {"transaction": tv, "suggestion": sv}


@router.get("/statements/{sid}")
async def get_statement(sid: str, r: Repos = Depends(repos)) -> dict:
    detail = await svc.statement_detail(r, check_id(sid))
    if detail is None:
        raise HTTPException(404, "statement not found")
    return {"statement": serialize(detail["statement"]), "rows": [_row_view(x) for x in detail["rows"]]}


@router.get("/statements/{sid}/export.csv")
async def export_statement(sid: str, r: Repos = Depends(repos)) -> StreamingResponse:
    detail = await svc.statement_detail(r, check_id(sid))
    if detail is None:
        raise HTTPException(404, "statement not found")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row", "date", "narration", "reference", "amount", "currency", "status", "suggested", "score",
                "band", "reason"])
    for row in detail["rows"]:
        t, s = row["transaction"], row["suggestion"] or {}
        w.writerow([t["row_no"], t["txn_date"], spreadsheet_safe(t["narration"]), spreadsheet_safe(t["reference"]),
                    format_amount(t["amount_minor"], t["currency"], symbol=False), t["currency"], t["status"],
                    " + ".join(a["invoice_number"] for a in s.get("allocations", [])), s.get("score", ""),
                    s.get("band", ""), spreadsheet_safe(s.get("reason", ""))])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="reconciliation-{sid}.csv"'})


class ApproveIn(BaseModel):
    invoice_numbers: list[str] | None = Field(default=None, max_length=10)
    close_with_tds: bool = False


@router.post("/suggestions/{sug_id}/approve")
async def approve(sug_id: str, body: ApproveIn, r: Repos = Depends(repos), user: str = Depends(require_user)):
    numbers = [check_invoice_number(n) for n in body.invoice_numbers] if body.invoice_numbers else None
    return await svc.approve(r, check_id(sug_id), user, numbers, body.close_with_tds)


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/suggestions/{sug_id}/reject")
async def reject(sug_id: str, body: RejectIn, r: Repos = Depends(repos), user: str = Depends(require_user)):
    await svc.reject(r, check_id(sug_id), user, body.reason)
    return {"ok": True}
