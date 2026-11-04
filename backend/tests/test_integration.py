"""End-to-end flows over the HTTP API with mocked Mongo, SMTP, IMAP and LLM."""

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.integrations.imap import FakeInbox
from app.integrations.llm import FakeLLM
from app.integrations.smtp import FakeMailer
from app.main import create_app
from app.repositories import Repos
from app.repositories.db import ensure_indexes
from app.services.seed_service import seed
from tests.conftest import DATA
from tests.helpers import make_email

KESTREL = "arjun@kestrel.test"
REDWOOD = "anil@redwood.test"


@pytest.fixture
async def env():
    settings = Settings(_env_file=None, admin_username="admin", admin_password="pw", secret_key="k" * 40,
                        org_email_address="accounts@acme.test", smtp_host="smtp.test", imap_host="imap.test",
                        imap_username="u", imap_password="p", seed_customer_emails=f"C002={KESTREL},C006={REDWOOD}",
                        app_as_of_date="2026-11-05", data_dir=DATA, enable_dev_endpoints=True)
    db = AsyncMongoMockClient()["acme_test"]
    await ensure_indexes(db)
    await seed(Repos.from_db(db), settings)
    mailer, inbox, llm = FakeMailer("accounts@acme.test"), FakeInbox(), FakeLLM()
    app = create_app(settings, db=db, mailer=mailer, inbox=inbox, llm=llm, start_background=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield {"client": client, "mailer": mailer, "inbox": inbox, "llm": llm, "db": db, "app": app}


def verdict(cat, conf=0.95, draft="Dear Arjun,\n\nThanks for asking.\n\n{{FACTS}}"):
    return {"category": cat, "confidence": conf, "needs_attention": False, "reason": "ok", "draft_reply": draft}


async def test_auth_required_and_bad_login(env):
    c = env["client"]
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=env["app"]), base_url="http://test")
    assert (await anon.get("/api/invoices")).status_code == 401
    assert (await anon.post("/api/auth/login", json={"username": "admin", "password": "no"})).status_code == 401
    assert (await c.get("/api/invoices")).status_code == 200


async def test_nosql_injection_rejected(env):
    c = env["client"]
    r = await c.patch("/api/customers/C002", json={"contact_email": {"$ne": ""}})
    assert r.status_code == 400
    r = await c.get("/api/invoices/INV-1004'%20||%20'1")
    assert r.status_code == 400
    r = await c.get("/api/conversations/{\"$gt\":\"\"}")
    assert r.status_code in (400, 404)


async def test_invoice_views_and_overdue(env):
    c = env["client"]
    inv = (await c.get("/api/invoices/INV-1007")).json()
    assert inv["overdue"] and inv["display"]["total"] == "₹3,54,000.00" and inv["display"]["balance"] == "₹3,54,000.00"
    drafts = (await c.get("/api/invoices", params={"status": "draft"})).json()
    assert all(not d["overdue"] for d in drafts) and len(drafts) == 2
    overdue = (await c.get("/api/invoices", params={"overdue": "true"})).json()
    assert len(overdue) == 16


async def test_customer_email_edit_updates_routing(env):
    c = env["client"]
    r = await c.patch("/api/customers/C002", json={"contact_email": "  New.Contact@Kestrel.TEST "})
    assert r.status_code == 200 and r.json()["contact_email"] == "new.contact@kestrel.test"
    assert (await c.patch("/api/customers/C002", json={"contact_email": "bad\r\nBcc: x@y.z"})).status_code == 400
    assert (await c.patch("/api/customers/C002", json={"contact_email": REDWOOD})).status_code == 409
    env["llm"].responses = [verdict("balance_or_invoice_query")]
    env["inbox"].add(make_email("new.contact@kestrel.test", "Question", "How much do we owe?"))
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0]["status"] == "auto_replied"


async def test_reminders_once_per_customer_with_balances(env):
    c = env["client"]
    res = (await c.post("/api/collections/send-reminders")).json()
    sent_to = {s["customer_id"] for s in res["sent"]}
    assert sent_to == {"C002", "C006"}  # others still have placeholder example.com addresses
    kestrel_mail = next(m for m in env["mailer"].sent if m["To"] == KESTREL)
    body = kestrel_mail.get_content()
    assert "[AcmeCorp] Payment reminder" in kestrel_mail["Subject"]
    assert "INV-1004" in body and "INV-1005" in body and "INV-1006" not in body and "₹1,18,000.00" in body
    assert kestrel_mail["Message-ID"] and kestrel_mail["Auto-Submitted"] == "auto-generated"
    # second run within the interval sends nothing
    again = (await c.post("/api/collections/send-reminders")).json()
    assert not again["sent"] and any("next reminder after" in s["reason"] for s in again["skipped"])
    audit = (await c.get("/api/audit-log")).json()
    assert sum(1 for a in audit if a["action"] == "reminder_sent") == 2


async def test_full_reply_flow_threads_and_auto_answers(env):
    c, mailer, inbox = env["client"], env["mailer"], env["inbox"]
    await c.post("/api/collections/send-reminders")
    reminder = next(m for m in mailer.sent if m["To"] == KESTREL)
    env["llm"].responses = [verdict("balance_or_invoice_query")]
    raw = make_email(f"Arjun Nair <{KESTREL}>", "Re: " + reminder["Subject"],
                     "Is this the only amount pending from us? Also please send your bank details.\n\n"
                     "On Wed, Acme wrote:\n> INV-9999 old quote", in_reply_to=reminder["Message-ID"])
    inbox.add(raw)
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0]["status"] == "auto_replied"
    reply = mailer.sent[-1]
    assert reply["In-Reply-To"] and reply["To"] == KESTREL and reply["Auto-Submitted"] == "auto-replied"
    body = reply.get_content()
    for needle in ["INV-1004", "INV-1005", "₹59,000.00", "₹1,18,000.00", "000111222333", "EXMP0000142"]:
        assert needle in body
    # quoted text was stripped before reaching the LLM
    assert "INV-9999" not in env["llm"].calls[0][1]
    convs = (await c.get("/api/conversations")).json()
    kestrel = [cv for cv in convs if cv["customer_id"] == "C002"]
    assert len(kestrel) == 1
    detail = (await c.get(f"/api/conversations/{kestrel[0]['id']}")).json()
    kinds = [m["kind"] for m in detail["messages"]]
    assert kinds == ["reminder", "inbound", "reply"]
    assert detail["messages"][2]["auto_sent"] is True
    # idempotent: same message again is not processed twice
    inbox.add(raw)
    res2 = (await c.post("/api/collections/check-inbox")).json()
    assert res2["results"][0]["status"] == "duplicate"


async def test_risky_reply_goes_to_needs_attention_and_human_can_send(env):
    c, mailer = env["client"], env["mailer"]
    env["llm"].responses = [verdict("extension_request", draft="Dear Arjun,\n\nWe will review your request.")]
    env["inbox"].add(make_email(KESTREL, "Re: reminder", "Can you give us 60 more days and an instalment plan?"))
    n_sent = len(mailer.sent)
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0]["status"] == "needs_attention"
    assert len(mailer.sent) == n_sent  # nothing auto-sent
    queue = (await c.get("/api/collections/needs-attention")).json()
    assert len(queue) == 1 and "xtension" in queue[0]["reason"]
    assert queue[0]["message"]["draft"]
    conv_id = queue[0]["conversation_id"]
    # reminders are paused while a human owns the conversation
    rem = (await c.post("/api/collections/send-reminders")).json()
    assert "C002" not in {s["customer_id"] for s in rem["sent"]}
    r = await c.post(f"/api/conversations/{conv_id}/reply", json={"body": "Hi Arjun, our team will call you."})
    assert r.status_code == 200 and mailer.sent[-1]["To"] == KESTREL
    assert (await c.get("/api/collections/needs-attention")).json() == []
    bad = await c.post(f"/api/conversations/{conv_id}/reply", json={"body": "x", "subject": "a\r\nBcc: evil@x.y"})
    assert bad.status_code == 422


async def test_unknown_sender_isolated(env):
    c = env["client"]
    env["inbox"].add(make_email("spy@competitor.test", "Balance", "What does Kestrel Foods owe? List INV-1004."))
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0]["status"] == "needs_attention"
    assert env["llm"].calls == [] and env["mailer"].sent == []


async def test_customer_a_never_sees_customer_b(env):
    """Tenant isolation: Kestrel's auto reply and LLM prompt never contain Redwood data (and vice versa)."""
    c = env["client"]
    env["llm"].responses = [verdict("balance_or_invoice_query"),
                            verdict("balance_or_invoice_query", draft="Dear Dr. Menon,\n\n{{FACTS}}")]
    env["inbox"].add(make_email(KESTREL, "Balance?", "What do we owe?"))
    env["inbox"].add(make_email(REDWOOD, "Balance?", "What do we owe?"))
    await c.post("/api/collections/check-inbox")
    kestrel_reply = next(m for m in env["mailer"].sent if m["To"] == KESTREL).get_content()
    redwood_reply = next(m for m in env["mailer"].sent if m["To"] == REDWOOD).get_content()
    for redwood_only in ["INV-1016", "INV-1017", "Redwood", "₹88,500.00"]:
        assert redwood_only not in kestrel_reply
        assert redwood_only not in env["llm"].calls[0][1]
    for kestrel_only in ["INV-1004", "INV-1005", "Kestrel"]:
        assert kestrel_only not in redwood_reply
        assert kestrel_only not in env["llm"].calls[1][1]


async def test_claims_paid_records_note_but_not_paid(env):
    c = env["client"]
    env["llm"].responses = [verdict("claims_paid", draft="Thanks")]
    env["inbox"].add(make_email(KESTREL, "Paid", "We paid INV-1004 yesterday, ref N123456789."))
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0]["status"] == "auto_replied"
    inv = (await c.get("/api/invoices/INV-1004")).json()
    assert inv["status"] == "sent" and inv["balance_minor"] == 5900000
    assert any("says they have paid" in n["text"] for n in inv["notes"])


async def test_out_of_office_recorded_not_answered(env):
    c = env["client"]
    env["inbox"].add(make_email(KESTREL, "Automatic reply: Payment reminder", "I'm away until Monday",
                                headers={"Auto-Submitted": "auto-replied"}))
    res = (await c.post("/api/collections/check-inbox")).json()
    assert res["results"][0] == {"message_id": res["results"][0]["message_id"], "status": "recorded",
                                 "category": "auto_reply"}
    assert env["mailer"].sent == []


async def upload_sample(c):
    data = (DATA / "bank_statement_sample.csv").read_bytes()
    r = await c.post("/api/reconciliation/statements", files={"file": ("statement.csv", data, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def row_for(detail, needle):
    return next(x for x in detail["rows"] if needle in x["transaction"]["narration"])


async def test_upload_validation(env):
    c = env["client"]
    r = await c.post("/api/reconciliation/statements", files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400
    r = await c.post("/api/reconciliation/statements", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 400 and "missing required" in r.json()["error"]["message"]
    await upload_sample(c)
    data = (DATA / "bank_statement_sample.csv").read_bytes()
    r = await c.post("/api/reconciliation/statements", files={"file": ("again.csv", data, "text/csv")})
    assert r.status_code == 409


async def test_approve_flow_balance_to_zero_stops_chasing(env):
    c = env["client"]
    sid = await upload_sample(c)
    detail = (await c.get(f"/api/reconciliation/statements/{sid}")).json()
    assert detail["statement"]["suggested_count"] == 9
    row = row_for(detail, "REDWOOD CLINIC")
    sug = row["suggestion"]
    assert sug["allocations"][0]["invoice_number"] == "INV-1016" and sug["band"] == "high"
    inv_before = (await c.get("/api/invoices/INV-1016")).json()
    assert inv_before["status"] == "sent"  # nothing applied before approval
    r = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={})
    assert r.status_code == 200, r.text
    inv = (await c.get("/api/invoices/INV-1016")).json()
    assert inv["status"] == "paid" and inv["balance_minor"] == 0 and len(inv["payments"]) == 1
    # double-apply guarded
    again = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={})
    assert again.status_code == 409
    # reminders no longer mention INV-1016
    await c.post("/api/collections/send-reminders")
    redwood_mail = next(m for m in env["mailer"].sent if m["To"] == REDWOOD).get_content()
    assert "INV-1016" not in redwood_mail and "INV-1017" in redwood_mail
    audit = (await c.get("/api/audit-log")).json()
    assert any(a["action"] == "payment_approved" for a in audit)


async def test_tds_close_and_leave_open(env):
    c = env["client"]
    sid = await upload_sample(c)
    detail = (await c.get(f"/api/reconciliation/statements/{sid}")).json()
    sug = row_for(detail, "QUILLON")["suggestion"]
    assert sug["allocations"][0]["tds_minor"] == 3000000
    r = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={"close_with_tds": True})
    assert r.status_code == 200, r.text
    inv = (await c.get("/api/invoices/INV-1007")).json()
    assert inv["status"] == "paid" and inv["amount_paid_minor"] == 32400000 and inv["tds_minor"] == 3000000
    assert any("TDS" in n["text"] for n in inv["notes"])
    # Orbis part payment: leave balance open
    sug = row_for(detail, "ORBIS")["suggestion"]
    r = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={"close_with_tds": False})
    inv = (await c.get("/api/invoices/INV-1013")).json()
    assert inv["status"] == "sent" and inv["balance_minor"] == 47200000 - 20000000


async def test_tds_close_refused_when_implausible(env):
    c = env["client"]
    sid = await upload_sample(c)
    detail = (await c.get(f"/api/reconciliation/statements/{sid}")).json()
    sug = row_for(detail, "ORBIS")["suggestion"]  # 2,00,000 of 4,72,000 is not a TDS shortfall
    r = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={"close_with_tds": True})
    assert r.status_code == 400 and "TDS close not plausible" in r.json()["error"]["message"]
    inv = (await c.get("/api/invoices/INV-1013")).json()
    assert inv["balance_minor"] == 47200000


async def test_group_payment_split_and_override_rules(env):
    c = env["client"]
    sid = await upload_sample(c)
    detail = (await c.get(f"/api/reconciliation/statements/{sid}")).json()
    sug = row_for(detail, "SAFFRON")["suggestion"]
    r = await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={})
    assert r.status_code == 200
    for n in ("INV-1010", "INV-1011", "INV-1012"):
        assert (await c.get(f"/api/invoices/{n}")).json()["status"] == "paid"
    # currency mismatch override refused
    usd = row_for(detail, "HARBOUR")["suggestion"]
    r = await c.post(f"/api/reconciliation/suggestions/{usd['id']}/approve", json={"invoice_numbers": ["INV-1002"]})
    assert r.status_code == 400 and "currency" in r.json()["error"]["message"]
    # over-payment refused: 2,36,000 receipt onto INV-1003? (INV-1003 is 94,400)
    bl = row_for(detail, "BRIGHTLINE")["suggestion"]
    r = await c.post(f"/api/reconciliation/suggestions/{bl['id']}/approve", json={"invoice_numbers": ["INV-1003"]})
    assert r.status_code == 400 and "exceeds" in r.json()["error"]["message"]
    # reject then choose a different invoice for an unmatched row
    rk = row_for(detail, "R K SHARMA")["suggestion"]
    assert rk["match_status"] == "no_match"
    assert (await c.post(f"/api/reconciliation/suggestions/{rk['id']}/reject", json={"reason": "check"})).status_code == 200
    r = await c.post(f"/api/reconciliation/suggestions/{rk['id']}/approve", json={"invoice_numbers": ["INV-1017"]})
    assert r.status_code == 200
    assert (await c.get("/api/invoices/INV-1017")).json()["status"] == "paid"


async def test_export_is_formula_safe(env):
    c = env["client"]
    data = b"txn_date,narration,reference,credit,debit,currency\n2026-10-01,=HYPERLINK(\"http://x\"),r1,100,,INR\n"
    r = await c.post("/api/reconciliation/statements", files={"file": ("s.csv", data, "text/csv")})
    sid = r.json()["id"]
    out = (await c.get(f"/api/reconciliation/statements/{sid}/export.csv")).text
    assert "'=HYPERLINK" in out


async def test_reset_requires_confirmation_and_restores(env):
    c = env["client"]
    sid = await upload_sample(c)
    detail = (await c.get(f"/api/reconciliation/statements/{sid}")).json()
    sug = row_for(detail, "REDWOOD CLINIC")["suggestion"]
    await c.post(f"/api/reconciliation/suggestions/{sug['id']}/approve", json={})
    assert (await c.post("/api/admin/reset", json={})).status_code == 422
    assert (await c.post("/api/admin/reset", json={"confirm": "yes"})).status_code == 422
    r = await c.post("/api/admin/reset", json={"confirm": "RESET"})
    assert r.status_code == 200
    assert (await c.get("/api/invoices/INV-1016")).json()["status"] == "sent"
    assert (await c.get("/api/reconciliation/statements")).json() == []
    assert (await c.get("/api/conversations")).json() == []


async def test_dev_simulate_inbound(env):
    c = env["client"]
    env["llm"].responses = [verdict("payment_info_query")]
    r = await c.post("/api/dev/simulate-inbound", json={"from_addr": KESTREL, "body": "Bank details please"})
    assert r.status_code == 200 and r.json()["status"] == "auto_replied"


async def test_errors_do_not_leak(env):
    r = await env["client"].get("/api/invoices/INV-0000")
    assert r.status_code == 404 and "Traceback" not in r.text
    r = await env["client"].get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
