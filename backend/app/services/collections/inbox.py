"""Process inbound email: dedupe, thread, decide, act."""
from __future__ import annotations

import hashlib
import logging
import re

from app.core import clock
from app.core.config import Settings
from app.integrations.imap import InboxReader
from app.integrations.llm import LLMClient
from app.integrations.smtp import Mailer, MailError, OutgoingMail
from app.repositories import Repos
from app.services.collections import templates as T
from app.services.collections.agent import Decision, ReplyContext, decide
from app.services.collections.email_parse import InboundEmail, parse_email, strip_quoted

log = logging.getLogger(__name__)
_INV = re.compile(r"\bINV[\s\-/#:.]*0*(\d{3,6})\b", re.IGNORECASE)


async def process_inbox(repos: Repos, reader: InboxReader, mailer: Mailer, llm: LLMClient,
                        settings: Settings) -> dict:
    results = []
    processed_uids = []
    for uid, raw in await reader.fetch_unseen():
        try:
            results.append(await process_raw(repos, raw, mailer, llm, settings))
            processed_uids.append(uid)
        except Exception:
            log.exception("failed to process message uid=%s", uid)
            results.append({"status": "error"})
    await reader.mark_seen(processed_uids)
    return {"fetched": len(results), "results": results}


async def _thread(repos: Repos, mail: InboundEmail) -> tuple[str | None, str | None]:
    """Return (conversation_id, customer_id) via headers first, then sender address."""
    ids = [i for i in [mail.in_reply_to, *mail.references] if i]
    conv_id = await repos.collections.find_conversation_by_message_ids(ids)
    if conv_id:
        conv = await repos.collections.get_conversation(conv_id)
        if conv:
            return conv_id, conv.get("customer_id")
    customer = await repos.master.find_customer_by_email(mail.from_addr) if mail.from_addr else None
    if customer:
        conv = await repos.collections.latest_conversation_for_customer(customer.customer_id)
        if conv and conv.get("status") != "resolved":
            return conv["_id"], customer.customer_id
        return None, customer.customer_id
    return None, None


async def process_raw(repos: Repos, raw: bytes, mailer: Mailer, llm: LLMClient, settings: Settings) -> dict:
    mail = parse_email(raw)
    if not mail.message_id:  # synthesize a stable id so dedupe still works
        mail.message_id = f"<sha256-{hashlib.sha256(raw).hexdigest()[:40]}@inbound.local>"
    if await repos.collections.message_exists(mail.message_id):
        return {"message_id": mail.message_id, "status": "duplicate"}
    org = await repos.master.get_organization()
    assert org is not None
    if mail.from_addr and mail.from_addr == (settings.org_email_address or org.accounts_email).lower():
        return {"message_id": mail.message_id, "status": "own_message_ignored"}

    conv_id, customer_id = await _thread(repos, mail)
    customer = await repos.master.get_customer(customer_id) if customer_id else None
    sender_is_contact = customer is not None and mail.from_addr == customer.contact_email
    if conv_id is None:
        conv = await repos.collections.create_conversation(customer_id, mail.subject or "(no subject)")
        conv_id = conv["_id"]

    history = [{"direction": m["direction"], "text": m.get("body_text", "")}
               for m in await repos.collections.list_messages(conv_id)]
    clean = strip_quoted(mail.body_text)
    inbound_doc = {
        "message_id": mail.message_id, "conversation_id": conv_id, "direction": "in", "kind": "inbound",
        "from_addr": mail.from_addr, "from_name": mail.from_name, "to_addr": ", ".join(mail.to_addrs),
        "subject": mail.subject, "body_text": mail.body_text, "clean_text": clean,
        "in_reply_to": mail.in_reply_to, "references": mail.references,
        "received_at": mail.date, "processed_at": None,
    }
    if not await repos.collections.insert_message(inbound_doc):
        return {"message_id": mail.message_id, "status": "duplicate"}

    open_invoices = await repos.master.open_invoices(customer.customer_id) if customer else []
    all_numbers = {i.invoice_number for i in await repos.master.list_invoices(customer.customer_id)} if customer \
        else set()
    ctx = ReplyContext(mail=mail, clean_text=clean, customer=customer, open_invoices=open_invoices,
                       customer_invoice_numbers=all_numbers, org=org,
                       all_customers=await repos.master.list_customers(), history=history,
                       today=clock.today(), sender_is_contact=sender_is_contact)
    decision = await decide(ctx, llm)
    return await _act(repos, mailer, mail, conv_id, customer, decision, inbound_doc["_id"])


async def _act(repos: Repos, mailer: Mailer, mail: InboundEmail, conv_id: str, customer, decision: Decision,
               inbound_id: str) -> dict:
    now = clock.now()
    await repos.collections.update_message(inbound_id, {
        "category": decision.category, "confidence": decision.confidence, "action": decision.action,
        "reason": decision.reason, "llm_used": decision.llm_used, "processed_at": now,
        "needs_attention": decision.action == "needs_attention", "draft": decision.draft,
        "kind": "auto_reply" if decision.category == "auto_reply" else "inbound",
    })
    if decision.note:
        note = {"at": now.isoformat(), "kind": decision.category, "text": decision.note}
        await repos.collections.update_conversation(conv_id, {}, push={"notes": note})
        mentioned = {f"INV-{n}" for n in _INV.findall(mail.body_text)}
        open_nums = {i.invoice_number for i in await repos.master.open_invoices(customer.customer_id)}
        for number in sorted(mentioned & open_nums) or sorted(open_nums):
            await repos.master.add_invoice_note(number, note)

    if decision.action == "auto_send" and decision.reply_body and customer:
        subject = T.reply_subject(mail.subject)
        try:
            mid = await mailer.send(OutgoingMail(customer.contact_email, subject, decision.reply_body,
                                                 in_reply_to=mail.message_id, references=mail.references,
                                                 auto_submitted="auto-replied"))
        except MailError as exc:
            await repos.collections.update_message(inbound_id, {"needs_attention": True, "action": "needs_attention",
                                                                 "reason": f"Auto-reply could not be sent: {exc}",
                                                                 "draft": decision.reply_body})
            await repos.collections.update_conversation(conv_id, {"status": "needs_attention",
                                                                  "attention_reason": str(exc)})
            return {"message_id": mail.message_id, "status": "needs_attention", "category": decision.category}
        await repos.collections.insert_message({
            "message_id": mid, "conversation_id": conv_id, "direction": "out", "kind": "reply",
            "from_addr": "", "to_addr": customer.contact_email, "subject": subject, "body_text": decision.reply_body,
            "auto_sent": True, "category": decision.category, "in_reply_to": mail.message_id,
        })
        await repos.collections.update_conversation(conv_id, {"status": "open", "attention_reason": None})
        await repos.audit.log("agent", "auto_reply_sent", f"conversation:{conv_id}",
                              {"to": customer.contact_email, "category": decision.category, "message_id": mid})
        return {"message_id": mail.message_id, "status": "auto_replied", "category": decision.category}

    if decision.action == "needs_attention":
        await repos.collections.update_conversation(conv_id, {"status": "needs_attention",
                                                              "attention_reason": decision.reason})
        return {"message_id": mail.message_id, "status": "needs_attention", "category": decision.category,
                "reason": decision.reason}
    return {"message_id": mail.message_id, "status": "recorded", "category": decision.category}


async def send_human_reply(repos: Repos, mailer: Mailer, conv_id: str, body: str, actor: str,
                           subject: str | None = None) -> dict:
    conv = await repos.collections.get_conversation(conv_id)
    if conv is None:
        raise LookupError("conversation not found")
    messages = await repos.collections.list_messages(conv_id)
    last_in = next((m for m in reversed(messages) if m["direction"] == "in"), None)
    if conv.get("customer_id"):
        customer = await repos.master.get_customer(conv["customer_id"])
        to = customer.contact_email if customer else None
    else:
        to = last_in["from_addr"] if last_in else None  # unknown sender: reply only to them
    if not to:
        raise ValueError("no recipient for this conversation")
    subj = subject or T.reply_subject(last_in["subject"] if last_in else conv.get("subject", ""))
    refs = (last_in.get("references") or []) if last_in else []
    mid = await mailer.send(OutgoingMail(to, subj, body, in_reply_to=last_in["message_id"] if last_in else None,
                                         references=refs))
    await repos.collections.insert_message({
        "message_id": mid, "conversation_id": conv_id, "direction": "out", "kind": "human_reply",
        "to_addr": to, "subject": subj, "body_text": body, "auto_sent": False, "sent_by": actor,
    })
    for m in messages:
        if m.get("needs_attention"):
            await repos.collections.update_message(m["_id"], {"needs_attention": False, "handled_by": actor})
    await repos.collections.update_conversation(conv_id, {"status": "resolved", "attention_reason": None})
    await repos.audit.log(actor, "human_reply_sent", f"conversation:{conv_id}", {"to": to, "message_id": mid})
    return {"message_id": mid, "to": to}


async def resolve_conversation(repos: Repos, conv_id: str, actor: str, note: str | None = None) -> None:
    conv = await repos.collections.get_conversation(conv_id)
    if conv is None:
        raise LookupError("conversation not found")
    for m in await repos.collections.list_messages(conv_id):
        if m.get("needs_attention"):
            await repos.collections.update_message(m["_id"], {"needs_attention": False, "handled_by": actor})
    push = {"notes": {"at": clock.now().isoformat(), "kind": "resolved", "text": note}} if note else None
    await repos.collections.update_conversation(conv_id, {"status": "resolved", "attention_reason": None}, push=push)
    await repos.audit.log(actor, "conversation_resolved", f"conversation:{conv_id}", {"note": note})
