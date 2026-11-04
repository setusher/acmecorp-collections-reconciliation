# AcmeCorp Collections & Bank Reconciliation

AcmeCorp's Accounts Team uses this app after an invoice is sent:

1. **Collections agent.** It emails customers about overdue invoices, reads their replies over IMAP, answers routine questions with an LLM (every figure comes from the database and is checked before sending), and sends anything risky to a human in the **Needs attention** queue.
2. **Bank reconciliation.** Upload a bank statement CSV. For each receipt the app suggests which invoice(s) it pays, with a 0–100 confidence score and a one-line reason. A person approves, rejects or picks a different invoice. Only an approved match changes an invoice balance. When a balance reaches zero the invoice becomes `paid` and the agent stops chasing it.

Nothing financial changes without a human approval.

```
backend/    FastAPI + Motor (MongoDB). routes/ -> services/ -> repositories/ -> integrations/
frontend/   React + Vite + TypeScript + Tailwind (talks only to /api)
data/       the given data, unchanged
docs/       PLAN.md, explanation.md (-> explanation.pdf), VIDEO_SCRIPT.md, CONCEPTS_NOTES.md
docker-compose.yml   MongoDB (+ optional local test mail server)
.env.example         every setting, placeholders only
```

---

## 1. Quick start (about 10 minutes)

### Prerequisites
- **Docker** (for MongoDB; optionally a local test mail server)
- **Python 3.11+**. The commands below use [`uv`](https://docs.astral.sh/uv/); plain `python -m venv` + `pip` also works.
- **Node.js 20+** and npm

### Steps
```bash
git clone https://github.com/setusher/acmecorp-collections-reconciliation.git
cd acmecorp-collections-reconciliation

# 1. Configuration: copy and edit (see section 2 for each value)
cp .env.example .env

# 2. MongoDB
docker compose up -d mongo

# 3. Backend
cd backend
uv venv --python 3.12 .venv
uv pip install -p .venv/bin/python -e ".[dev]"    # or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m scripts.seed                  # loads data/*.json (safe to re-run)
.venv/bin/uvicorn app.main:app --port 8000        # API on http://localhost:8000, docs at /docs

# 4. Frontend (second terminal)
cd frontend
npm install
npm run dev                                       # UI on http://localhost:5173 (proxies /api to :8000)
```
Open http://localhost:5173 and sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`.

If the app runs on a remote machine, forward both ports: `ssh -L 5173:localhost:5173 -L 8000:localhost:8000 user@host`.

### Run the tests and the matching evaluation
```bash
cd backend
.venv/bin/pytest -q                       # 147 tests. No network: fake LLM, fake SMTP/IMAP, in-memory Mongo
.venv/bin/python -m scripts.eval_matching -v
```

---

## 2. Configuration (`.env`)

The backend reads `.env` from the repo root (or `backend/.env`). `.env` is git-ignored. Only `.env.example`, which holds placeholders, is committed.

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `MONGO_DB` | MongoDB connection (default `mongodb://localhost:27017`, `acmecorp`) |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Login for the UI/API. **Change the password.** |
| `SECRET_KEY` | Signs session tokens. Generate with `openssl rand -hex 32` |
| `FRONTEND_ORIGIN` | CORS allow-list (default `http://localhost:5173`) |
| `APP_AS_OF_DATE` | Optional `YYYY-MM-DD` that pins "today" (see section 6). Empty = real date |
| `ORG_EMAIL_ADDRESS` | The organization inbox. Also replaces `accounts_email` from `organization.json` at seed time |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_SSL` | Outgoing mail |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_SSL`, `IMAP_FOLDER` | Incoming mail |
| `INBOX_POLL_SECONDS` | Background inbox poll interval (default 60; `0` disables it; the **Check inbox now** button always works) |
| `REMINDER_INTERVAL_DAYS` | Minimum days between reminders to the same customer (default 7) |
| `REMINDER_SCHEDULE_MINUTES` | Optional scheduled reminder run (default 0 = manual only). Scheduled runs only send within the policy's working hours (Mon–Fri 10:00–18:00 IST) |
| `LLM_PROVIDER` | `gemini`, `groq`, `openai_compatible` or `none` |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` | LLM settings. The fallback model is tried if the first one fails |
| `SEED_CUSTOMER_EMAILS` | e.g. `C002=you.customer@gmail.com,C007=...`. Seeding and **Reset demo data** apply these overrides |
| `MAIL_TRANSPORT` | `smtp` (default) or `log` (dry run: messages are stored but not sent) |
| `ENABLE_DEV_ENDPOINTS` | `true` enables `POST /api/dev/simulate-inbound` (test replies without a mailbox) |

### 2.1 Two test mailboxes (Gmail)
You need **two separate mailboxes**: one for the organization (the app sends from it and reads it) and one that plays the customer. Plus-addresses of the same account do not work, because replies would come *from* the organization address.

For each Gmail account:
1. Turn on 2-Step Verification (Google Account → Security).
2. Create an **App password** (Google Account → Security → App passwords). It is a 16-character code.
3. IMAP is on by default in current Gmail. If needed, check Settings → See all settings → Forwarding and POP/IMAP.

Put the **organization** account in `.env`:
```
ORG_EMAIL_ADDRESS=acme.org.test@gmail.com
SMTP_HOST=smtp.gmail.com   SMTP_PORT=587  SMTP_STARTTLS=true  SMTP_SSL=false
SMTP_USERNAME=acme.org.test@gmail.com     SMTP_PASSWORD=<16-char app password>
IMAP_HOST=imap.gmail.com   IMAP_PORT=993  IMAP_SSL=true
IMAP_USERNAME=acme.org.test@gmail.com     IMAP_PASSWORD=<16-char app password>
```
Point one or more customers at the **customer** mailbox, either in `.env` before seeding:
```
SEED_CUSTOMER_EMAILS=C002=acme.customer.test@gmail.com
```
or later in the UI (**Customers → Edit**). Changing the email also changes how incoming mail is matched to that customer.

**No Gmail?** Run a local mail server with `docker compose --profile mail up -d greenmail` and use `SMTP_HOST=localhost SMTP_PORT=3025 SMTP_STARTTLS=false IMAP_HOST=localhost IMAP_PORT=3143 IMAP_SSL=false`. Any username and password are accepted. I used this to test the real SMTP/IMAP code end to end.

### 2.2 LLM provider (free tier)
- **Gemini:** create a key at https://aistudio.google.com/apikey, then set `LLM_PROVIDER=gemini`, `LLM_API_KEY=...`, and `LLM_MODEL` to a current free-tier model (`.env.example` lists one; model names change, so check the AI Studio model list).
- **Groq:** create a key at https://console.groq.com/keys, then set `LLM_PROVIDER=groq`, `LLM_API_KEY=...`, and `LLM_MODEL` to any chat model Groq lists.
- **Any OpenAI-compatible endpoint:** `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://.../v1`.
- `LLM_PROVIDER=none` disables the LLM. Every customer email then goes to **Needs attention** with a pre-filled, validated draft. Nothing crashes and nothing unvalidated is sent.

To swap provider, change these environment variables; the wrapper lives in `backend/app/integrations/llm.py`.

---

## 3. How to test each feature

| Feature | How |
|---|---|
| Invoices + Overdue badge | **Invoices** page. Filter *Overdue*. With `APP_AS_OF_DATE=2026-11-05` exactly 16 invoices are overdue. Drafts (INV-1006, INV-1019) never are |
| INR formatting | Amounts such as `₹3,54,000.00`; USD/EUR/GBP use standard grouping |
| Edit customer email | **Customers → Edit**. The value is validated and lowercased. A duplicate of another customer's email is refused |
| Send reminders | **Collections → Send reminders**. One email per customer lists all their overdue invoices (balances, due dates, bank details). Customers still on `@example.com` are skipped with a reason. A second click within `REMINDER_INTERVAL_DAYS` sends nothing |
| Be the customer | From the customer mailbox, **reply** to the reminder (or write a new email to the org address). Then click **Check inbox now** (or wait for the poller) |
| Auto-answer (required example) | Reply as Kestrel Foods (C002): *"is this the only amount pending from us? Also please send your bank details"*. The automatic reply lists INV-1004 and INV-1005 (₹59,000.00 each, due 19 Sep / 20 Oct 2026), total ₹1,18,000.00, and the bank details. It does not mention draft INV-1006 or paid INV-1020 |
| Risky reply | Reply *"we dispute INV-1005"*, *"can we have 60 more days?"* or *"our lawyer…"*. Nothing is sent; the conversation appears in **Needs attention** with the reason and a draft. Edit the draft and **Send reply**, or **Dismiss** |
| "I have paid" | Reply *"we paid INV-1004 yesterday, ref N123456789"*. The app sends a polite acknowledgement and records a note on the conversation and the invoice. **The invoice stays unpaid** until a bank match is approved |
| Unknown sender | Email the org inbox from an address that isn't a customer. It goes to Needs attention, no customer data is shared and the LLM is not called |
| Out-of-office / bounce | Auto-replies are recorded and not answered. Bounces go to Needs attention ("check the customer's email address") |
| Without a mailbox | Set `ENABLE_DEV_ENDPOINTS=true` and `POST /api/dev/simulate-inbound` `{"from_addr": "...", "body": "..."}` (runs the same pipeline as IMAP) |
| Bank reconciliation | **Bank Reconciliation → Upload statement CSV** with `data/bank_statement_sample.csv`. Review each row: **Approve**, **Reject**, or choose another invoice from the dropdown (alternatives first, then every open invoice in that currency) |
| TDS | Quillon row (₹3,24,000 against INV-1007, ₹3,54,000): *Close invoice (TDS deducted: ₹30,000)* is pre-selected. Approve it and INV-1007 becomes `paid` (cash ₹3,24,000 + TDS ₹30,000) |
| Partial payment | Orbis row (₹2,00,000 against ₹4,72,000): *Leave balance open*. The TDS option is disabled because the shortfall is not 10% of the subtotal |
| One payment, several invoices | Saffron Peak row (₹1,94,700 = INV-1010 + 1011 + 1012). Approval splits the receipt across all three |
| Paid -> no more chasing | Approve the Redwood row, then **Send reminders** (after the interval, or after **Reset demo data**). INV-1016 is no longer listed |
| Reset demo data | Sidebar → **Reset demo data**, then type `RESET` |
| Audit log | **Audit log** page: approvals, rejections, emails sent, customer edits, resets |

### Statement CSV format
`txn_date,narration,reference,credit,debit,currency` (one header row). The parser accepts a BOM, blank lines, surrounding whitespace, Indian grouping (`2,36,000.00`), currency symbols, and dates in `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD.MM.YYYY`, `DD-Mon-YYYY` and `DD Mon YYYY`. Ambiguous dates are read **day first** (Indian bank). Only credits are reconciled. A malformed row rejects the whole file with line-numbered errors. Limits: `.csv` only, 2 MB, 5,000 rows. Uploading the same file twice is refused; a row already imported from another statement is marked *duplicate* and not suggested again.

---

## 4. API

Everything is under `/api`. Interactive docs: http://localhost:8000/docs. All endpoints except `POST /auth/login` and `GET /health` need `Authorization: Bearer <token>`.

Errors always have the shape `{"error": {"code": "...", "message": "...", "details"?: [...]}}`. Status codes: 400 invalid input, 401 not signed in, 404 not found, 409 conflict (e.g. already applied), 422 validation, 429 rate limited, 502 mail server problem. Stack traces are never returned.

| Method & path | Purpose | Request | Response |
|---|---|---|---|
| `POST /auth/login` | Sign in (10/min per IP) | `{"username","password"}` | `{"token","username","expires_in_seconds"}` |
| `GET /health` | Liveness + DB ping | – | `{"ok","db"}` |
| `GET /system/status` | Today's date, mail/LLM configuration | – | `{"today","smtp_configured","imap_configured","llm_provider",...}` |
| `GET /organization` | Organization details, bank details, policies | – | organization object |
| `GET /customers` | Customers with open/overdue counts and outstanding total | – | `[{customer_id,name,contact_email,currency,open_count,overdue_count,outstanding_display,...}]` |
| `GET /customers/{id}` | One customer with all invoices | – | customer + `invoices[]` |
| `PATCH /customers/{id}` | Change contact email (validated, lowercased, unique) and/or payer aliases | `{"contact_email"?: str, "aliases"?: [str]}` | updated customer |
| `GET /invoices` | List invoices. Filters: `status=draft\|sent\|paid`, `customer_id=C00x`, `overdue=true\|false` | – | `[{invoice_number,status,currency,*_minor,overdue,days_overdue,display:{total,balance,...}}]` |
| `GET /invoices/{number}` | Invoice detail with line items, notes and approved payments | – | invoice + `line_items`, `notes`, `payments` |
| `POST /collections/send-reminders` | Send due reminders now (6/min) | `{}` | `{"sent":[{customer,to,invoices,reminder_number}],"skipped":[{customer,reason}]}` |
| `POST /collections/check-inbox` | Poll IMAP now (6/min) | `{}` | `{"fetched", "results":[{message_id,status,category,reason?}]}` |
| `GET /conversations` | Conversations. Filters: `status=open\|needs_attention\|resolved`, `customer_id` | – | `[{id,customer_name,status,subject,message_count,last_message,...}]` |
| `GET /conversations/{id}` | Thread with every message (direction, kind, category, auto_sent, reason) and notes | – | conversation + `messages[]` |
| `GET /collections/needs-attention` | The human queue | – | `[{conversation_id,customer_name,reason,message:{body_text,clean_text,draft,category,...}}]` |
| `POST /conversations/{id}/reply` | Human sends a reply (saved to the thread; resolves it) | `{"body": str, "subject"?: str}` | `{"message_id","to"}` |
| `POST /conversations/{id}/resolve` | Dismiss / resolve without replying | `{"note"?: str}` | `{"ok": true}` |
| `POST /reconciliation/statements` | Upload CSV (multipart field `file`; 10/min) | file | statement `{id,filename,row_count,credit_count,suggested_count,duplicate_count}` (201) |
| `GET /reconciliation/statements` | Uploaded statements | – | `[statement]` |
| `GET /reconciliation/statements/{id}` | Rows with their suggestion | – | `{"statement", "rows":[{"transaction","suggestion":{score,band,reason,allocations,alternatives,status}}]}` |
| `GET /reconciliation/statements/{id}/export.csv` | Export results (formula-injection safe) | – | CSV |
| `POST /reconciliation/suggestions/{id}/approve` | Apply the receipt. `invoice_numbers` overrides the suggestion; `close_with_tds` settles a plausible TDS shortfall | `{"invoice_numbers"?: [str], "close_with_tds": bool}` | `{"applied":[{invoice_number,amount_minor,tds_minor,new_balance_minor,new_status}]}` |
| `POST /reconciliation/suggestions/{id}/reject` | Reject the suggestion (a different invoice can still be approved later) | `{"reason"?: str}` | `{"ok": true}` |
| `POST /admin/reset` | Restore `data/`, clear transactional data (5/min) | `{"confirm": "RESET"}` (anything else → 422) | `{"ok": true, ...counts}` |
| `GET /audit-log?limit=200` | Audit trail | – | `[{at,actor,action,entity,details}]` |
| `POST /dev/simulate-inbound` | Only with `ENABLE_DEV_ENDPOINTS=true`. Inject a customer email | `{"from_addr","body","subject"?,"in_reply_to"?}` | same as one inbox result |

Money in API payloads is integer **minor units** (`*_minor`, e.g. paise) plus pre-formatted `display` strings.

---

## 5. How it works

### Collections agent
- **Eligible invoices:** `status == sent`, balance > 0, due date < today. Paid and draft invoices are never chased or shown to customers.
- **One reminder per customer.** The email lists all of that customer's overdue invoices. That is less mail for the customer and simpler threading. The facts block (invoice number, invoice date, due date, **balance** rather than total, currency, total outstanding, bank details, TDS or bank-charges policy) is generated from the DB by `services/collections/templates.py`. The LLM never writes reminders.
- **No spam:** each reminder is stored on the conversation. A customer is not reminded again within `REMINDER_INTERVAL_DAYS`, nor while their conversation is in Needs attention (open dispute, extension request and so on). Tone escalates from the 1st to the 2nd to the 3rd reminder.
- **Headers:** a unique `Message-ID`, the subject tag `[AcmeCorp] Payment reminder: ...`, and `In-Reply-To`/`References` on replies. `Auto-Submitted: auto-generated` / `auto-replied` (RFC 3834) stops our mail from triggering loops with auto-responders.
- **Inbound pipeline** (`services/collections/inbox.py`): dedupe by Message-ID (unique index; a synthetic SHA-256 id if missing) → thread by `In-Reply-To`/`References`, then by sender email → strip quoted history and signature → automated-mail detection → decide → act. A message is marked `\Seen` only after it is stored, so a crash never loses mail.
- **Decision** (`services/collections/agent.py`). The order matters, and the rules are code, not prompt:
  1. Auto-reply → record only. Bounce → Needs attention.
  2. Unknown sender → Needs attention; the LLM is not called and nothing is shared.
  3. Thread matched but the sender is not the customer's registered contact → Needs attention.
  4. SPF/DKIM/DMARC failure in `Authentication-Results` → Needs attention.
  5. Deterministic risk screen (legal words, dispute words, extension/instalment/waiver words, invoice numbers that aren't this customer's, other customers' names). These force Needs attention whatever the LLM says.
  6. LLM classification → JSON `{category, confidence, needs_attention, reason, draft_reply}`, validated with Pydantic.
  7. `balance_or_invoice_query` / `payment_info_query` with confidence ≥ 0.7: the LLM's wording plus the code-generated facts block go through the **validator**. If validation fails, the app retries once with the validator's feedback, then sends to Needs attention.
  8. `claims_paid` / `promises_to_pay`: a template acknowledgement plus a note on the conversation and invoice. **Never** marks anything paid.
  9. Extension, dispute, legal, other company, unknown, low confidence or LLM error: Needs attention with a draft. The draft is the LLM's only if it passes validation; otherwise it is a neutral holding reply.
- **Validator** (`services/collections/validator.py`): extracts every invoice number, amount (with or without a currency marker, Indian or western grouping), date (ISO, `19 Sep 2026`, `September 19, 2026`, `19/09/2026`), long account-like number and IFSC/SWIFT code. Each must be in the customer's allowed set: their open invoices' numbers; their balances and the sum of those balances; those invoices' invoice and due dates; the organization's account number and bank codes. Another currency, or another customer's name, also fails validation.
- **Prompt-injection defence:** the email sits between `<<<CUSTOMER_EMAIL>>>` markers (marker strings inside the body are neutralised), and the system prompt says it is untrusted data. The prompt is not the real protection, though. The real protection is that the LLM has no tools, cannot trigger actions, never sees other customers' data, and every outgoing text passes the validator and the code rules.

### Bank reconciliation matching (local, deterministic, no LLM)
See `docs/explanation.md` for the full rationale. In short:
1. **Normalise** the narration: drop transfer rails (NEFT/RTGS/IMPS/UPI/SWIFT/SEPA), CR/DR, months, payment words, reference-like tokens, company suffixes (PVT, LTD, LLP, INC, GMBH, …) and initials.
2. **Invoice numbers:** `INV-1002`, `INV 1002`, `INV1002`, `INV/1002`, `inv#1002`, lists like `INV 1010/1011`. A bare `RE 1024` counts as weaker evidence, and only if it belongs to the identified payer. PO numbers also count.
3. **Payer:** an ensemble per customer name or alias. **IDF-weighted anchored token coverage** (tolerates truncation TECH→TECHNOLOGIES, abbreviation PKG→PACKAGING and BRIGHTLN→BRIGHTLINE, typos KESTRAL→KESTREL, glued KESTRELFOODS) 55% + rapidfuzz `token_set_ratio` 15% + char-3-gram TF-IDF cosine 15% + Jaro-Winkler 10% + Jaccard 5%. A payer is *identified* only if a distinctive token matched, the score is ≥ 0.60, and it leads the runner-up by ≥ 0.10. Generic words (RETAIL, CLINIC, MEDIA…) can never identify a payer on their own.
4. **Candidates:** `sent`, balance > 0, **same currency**. Single invoices, plus subsets of 2–5 of the payer's open invoices (subset-sum).
5. **Score (0–100):** payer ≤ 45, amount (balance 40 / TDS 35 / subset 33 / declared partial 25 / instalment 22 / other partial 8), explicit invoice number 25 (bare 15), PO 20, date +5 / −50 if before the invoice date, customer email evidence +10/+20. Penalties apply for conflicting evidence. **Ambiguity:** if the runner-up is within 10 points, the score drops by 10–20, oldest-due wins, and the reason says so.
6. **Bands:** ≥ 85 high, 65–84 medium, 40–64 low, < 40 **No match** (the top 3 are still shown as leads). Hard caps: no identified payer and no invoice number → never above 35; payer and invoice number pointing at different customers → 35; a receipt that doesn't settle the invoice → never "high".

**Results on the sample statement and 25 synthetic tricky cases (`scripts/eval_matching.py`):**
```
cases 37 · suggested 25 · correct 25 · wrong 0 · missed 0 · correct "no match" 12
precision 1.000 · recall 1.000 · band violations 0
```
All 12 credit rows of the sample get the expected answer, including the TDS case, `RE 1024`, the three-invoice payment, and the two traps that must stay unmatched (`R K SHARMA` paying exactly INV-1017's amount, and `MAPLE RETAIL SERVICES`). **Caveat:** I wrote the synthetic cases while building the scorer, so they are a regression suite, not an independent hold-out. The hidden statement will be the real test.

### Approvals
`POST /approve` checks everything before changing anything: same currency, invoices open, a single customer, no over-payment, and a TDS close allowed only for INR when the shortfall equals 10% of the subtotal (±₹1). It then claims the transaction atomically (`suggested|unmatched|rejected → applying`), so the same receipt can never be applied twice, even with two tabs. Each invoice update is a guarded atomic `$inc` (`balance_minor >= amount` in the filter). If a multi-invoice approval fails half-way, the earlier invoices are reverted. TDS is stored as its own `tds_minor` component, so the audit trail shows *why* the balance is zero. Every approval creates `payments` records, invoice notes and an audit entry.

---

## 6. Design decisions and assumptions
- **"Today"** comes only from `app/core/clock.py::today()`. `APP_AS_OF_DATE=YYYY-MM-DD` pins it, for deterministic demos and tests; the test suite pins 2026-11-05. Leave it empty in normal use.
- **One reminder email per customer**, not one per invoice (see above).
- **Reminder cadence:** `organization.json` has no dunning cadence, so I chose `REMINDER_INTERVAL_DAYS=7` (configurable), tone escalation by reminder number, and scheduled runs only within the stated working hours. Customers with an open human conversation are not chased.
- **Placeholder addresses** (`@example.com/.org/.net`) are never emailed. Reminders skip them with a reason.
- **TDS** is offered only for INR invoices with no earlier payment or TDS, where the shortfall equals 10% of the **subtotal** (the policy says subtotal, so for INV-1012 with a ₹5,000 discount the TDS is ₹6,500). A ₹1 tolerance covers rounding.
- **No bank-fee tolerance.** Policy: *"International customers must cover their own bank charges in full"*. A short SWIFT receipt is therefore a partial payment for a human to review, never silently absorbed.
- **Over-payment** is never applied automatically. The approver must choose invoices that the receipt covers exactly, or apply part of a receipt to one invoice.
- **Money** is stored as integer minor units, converted from the JSON with `Decimal(str(x))`. Display formatting is done in one backend function and mirrored in the browser only for values the browser computes.
- **Re-running the seed** inserts only what is missing. `--reset` (or the UI button) restores the original data and clears conversations, messages, payments, statements and suggestions.
- **MongoDB without a replica set** (single container) means no multi-document transactions. Integrity relies on atomic single-document updates with guards, plus compensation (see Approvals).
- Optional items I deliberately left out: sentence embeddings and an LLM pass over ambiguous reconciliation rows. The local algorithm already explains each decision, and the brief said wrong matches cost more than missed ones.

## 7. Security considerations
- **Secrets** come only from environment variables. `.env` is git-ignored and `.env.example` has placeholders. Logs never include keys or prompts (LLM errors log provider, model, HTTP status and exception type only). I checked the git history for secrets before submitting.
- **Auth:** a single admin login. The token is signed with itsdangerous (HMAC, 12 h expiry), credentials are compared in constant time, and login is rate-limited. The token lives in `sessionStorage`.
- **Input validation:** Pydantic models with lengths and patterns. Path ids are checked against strict regexes (`^[a-f0-9]{32}$`, `^INV-\d+$`, `^C\d+$`). Every query is built from typed values, never from raw request bodies. A middleware also rejects any JSON body containing `$`-prefixed keys (`{"$ne": ...}`), as defence in depth against **NoSQL injection**.
- **Tenant isolation:** LLM context, drafts and validator allow-lists are built from the matched customer only. Tests prove Kestrel's prompt and reply never contain Redwood's data and vice versa. Unknown senders get nothing.
- **Email safety:** CR/LF is rejected in subjects and addresses (header injection). HTML emails are converted to text server-side. The UI renders email bodies as plain text in `<pre>`; there is no `dangerouslySetInnerHTML` anywhere (XSS).
- **Uploads:** `.csv` only, content-type check, 2 MB, 5,000 rows, binary rejected, duplicate files refused. Exported CSV cells starting with `= + - @` are prefixed with `'` (formula injection).
- **Rate limits** (per IP, in memory): login, upload, check-inbox, send-reminders, reset.
- **CORS** is locked to `FRONTEND_ORIGIN`. Security headers are set (`nosniff`, `X-Frame-Options: DENY`, a restrictive CSP on API responses, `no-store`), and the UI has a CSP meta tag.
- **Errors** are consistent JSON without stack traces. Unhandled errors are logged server-side only.
- **Audit log:** approvals, rejections, resets, customer edits, and every email sent (reminders, auto replies, human replies).
- **Prompt injection:** see section 5. The LLM can't act and can't see other customers, and its text is validated.

## 8. Known limitations
- I tested the LLM path with a fake LLM and with mocked HTTP responses for Gemini and Groq, but **I have not run it against a live provider key**. Please set a key and try the Kestrel example.
- The real SMTP/IMAP code was tested end to end against a local GreenMail server, not against Gmail itself.
- Sender identity is the `From` address plus the receiving server's SPF/DKIM/DMARC verdict, when present. No cryptographic verification is done in-app.
- One admin user; no roles. The rate limiter is in-memory and per process.
- Reconciliation does not handle FX conversion (a receipt in a different currency never matches) or credit notes.
- I tuned the payer matcher on the nine given customers; very different names may need aliases (editable per customer).
- The background poller and the reminder scheduler run inside the API process. Run one backend instance.

## 9. Status

| Area | Item | Status |
|---|---|---|
| A | Seed (idempotent, email overrides), pages: Organization, Customers, Invoices, Collections, Bank Reconciliation | Done |
| A | Overdue computed via `clock.today()` / `APP_AS_OF_DATE`; drafts never overdue | Done |
| A | Edit customer email (validated, lowercased, unique) → inbound matching | Done |
| A | Reset demo data (confirm dialog + server-side `"RESET"` guard) | Done |
| A | Integer minor units, Indian grouping | Done |
| B | Reminders: one per customer, DB-generated facts, interval, no chasing paid invoices, headers, scheduled option | Done |
| B | IMAP poller + Check inbox now, Message-ID dedupe, threading, quote stripping | Done (tested against GreenMail) |
| B | LLM JSON classification, hard-coded routing rules, validator with retry, injection defence | Done (tested with fake LLM; live provider untested) |
| B | Required Kestrel example | Done (integration test) |
| B | Conversations + Needs attention UI (edit draft, send, dismiss) | Done |
| B (bonus) | Out-of-office / bounce detection | Done |
| C | Robust CSV upload, suggestions with score/band/reason/top-3 alternatives | Done |
| C | Approve / Reject / Choose different invoice; TDS close vs leave open; double-apply, over-pay and currency guards; audit | Done |
| C | Matching pipeline + `eval_matching.py` (precision 1.0, recall 1.0, 0 wrong on 37 cases) | Done |
| C (bonus) | One payment → several invoices (subset-sum, split on approval) | Done |
| C (bonus) | Customer "we paid … ref …" email linked as evidence to the statement row | Done |
| C (optional) | LLM pass over ambiguous rows; sentence embeddings | Not done (deliberately) |
| Docs | README, explanation.pdf, VIDEO_SCRIPT.md, CONCEPTS_NOTES.md | See `docs/` |
| Ops | Docker image for the whole stack | Not done (only MongoDB / GreenMail in compose) |
