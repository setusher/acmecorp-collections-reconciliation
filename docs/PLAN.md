# Plan

## Stack
- **Backend:** Python 3.12, FastAPI, Pydantic v2, Motor (async MongoDB), rapidfuzz, scikit-learn (TF-IDF char n-grams), httpx (LLM calls), smtplib/imaplib (stdlib), pytest.
- **DB:** MongoDB 7 via `docker-compose.yml`.
- **Frontend:** React 18 + Vite + TypeScript + Tailwind. Talks only to `/api`.
- **LLM:** `integrations/llm.py`, a provider-agnostic wrapper (Gemini / Groq / any OpenAI-compatible endpoint / `none`). The test suite uses a fake provider and never touches the network.
- **PDF:** `docs/explanation.md` is rendered to `explanation.pdf` by `docs/build_pdf.py` (markdown → HTML → headless Chromium).

## Folder layout
```
backend/
  app/
    main.py                 FastAPI app factory, CORS, error handlers, startup tasks
    core/                   config, clock, money, security (auth, rate limit, sanitizers), errors
    models/                 Pydantic domain + API schemas
    repositories/           Motor access, one module per collection group
    services/               business logic
      matching/             normalize, signals, payer, scorer, engine (pure, DB-free)
      collections/          reminders, inbound routing, reply agent, draft validator, templates
      reconciliation.py     statement upload, suggestions, approval
      csv_parser.py         robust bank CSV parsing
    integrations/           smtp, imap, llm
    routes/                 thin HTTP layer
  scripts/seed.py           idempotent loader for data/*.json (+ email overrides)
  scripts/eval_matching.py  precision/recall on sample CSV + synthetic cases
  tests/
frontend/src/{api,pages,components,lib}
data/                       given data (unchanged)
docs/                       PLAN, explanation.md, VIDEO_SCRIPT, CONCEPTS_NOTES
```

## Data model (MongoDB)
All money is stored as **integer minor units** (`*_minor`), converted with `Decimal(str(x))` at the edge.
- `organization` – one doc, copied from `organization.json` (accounts_email overridable by env).
- `customers` – `customer_id` (unique), name, contact, `contact_email` (lowercase, unique-ish index), currency, `aliases[]`.
- `invoices` – `invoice_number` (unique), customer_id, dates, currency, line items, `subtotal_minor`, `discount_minor`, `tax_minor`, `total_minor`, `amount_paid_minor`, `tds_minor`, `balance_minor`, status, notes[]. Overdue is computed, never stored.
- `conversations` – customer_id (nullable), subject, status (`open|needs_attention|resolved`), `thread_message_ids[]`, `last_reminder_at`, notes[].
- `messages` – `message_id` (**unique**), conversation_id, direction (in/out), from/to, subject, body_text, headers subset, category, confidence, auto_sent, kind (`reminder|reply|auto_reply|bounce|human_reply|inbound`), `needs_attention`, reason, draft, `processed_at`.
- `bank_statements` – filename, uploaded_at, row counts, sha256 (duplicate upload guard).
- `bank_transactions` – statement_id, row_no, date, narration, reference, `amount_minor`, direction, currency, `fingerprint` (unique: date+amount+currency+reference+narration), status (`unmatched|suggested|approved|rejected|ignored`).
- `match_suggestions` – transaction_id, allocations[{invoice_number, amount_minor, tds_minor}], score, band, reason, signals, alternatives[3], status.
- `payments` – transaction_id (unique per invoice), invoice_number, amount_minor, tds_minor, approved_by, approved_at.
- `audit_log` – ts, actor, action, entity, details.

## API (all under `/api`, bearer token except `/auth/login` and `/health`)
- `POST /auth/login`, `GET /health`
- `GET /organization`
- `GET /customers`, `GET /customers/{id}`, `PATCH /customers/{id}` (email, aliases)
- `GET /invoices` (filters: status, customer, overdue), `GET /invoices/{number}`
- `POST /admin/reset` (body must contain `{"confirm": "RESET"}`)
- `POST /collections/send-reminders`, `POST /collections/check-inbox`
- `GET /conversations`, `GET /conversations/{id}`, `GET /collections/needs-attention`
- `POST /conversations/{id}/reply` (human send), `POST /conversations/{id}/resolve`
- `POST /reconciliation/statements` (multipart CSV), `GET /reconciliation/statements`, `GET /reconciliation/statements/{id}`
- `POST /reconciliation/suggestions/{id}/approve` (optional invoice override / allocations, `close_with_tds`), `POST /reconciliation/suggestions/{id}/reject`
- `GET /audit-log`

## Matching algorithm (local, deterministic)
1. **Gate:** only credit rows. Interest/charges narrations → "bank entry, no customer".
2. **Normalize** narration: uppercase, split on punctuation, drop transfer/noise tokens (NEFT, RTGS, IMPS, UPI, SWIFT, SEPA, CR, DR, REF, TRF…), reference-like tokens (digits mixed with letters, long digit runs), company suffixes (PVT, LTD, LIMITED, LLP, INC, GMBH…).
3. **Invoice numbers:** `INV[\s\-/#.:]*\d+` (strong) plus bare tokens equal to a known invoice number of the identified payer (weak, e.g. `RE 1024`).
4. **Payer score** per customer = weighted ensemble of: anchored token coverage (IDF-weighted, with abbreviation/prefix/typo-tolerant token similarity – the main signal), rapidfuzz `token_set_ratio`, char 3-gram TF-IDF cosine, token Jaccard. A customer is "identified" only if its distinctive (high-IDF) token is matched and the score clears a threshold with a margin over the runner-up.
5. **Candidates:** invoices with status `sent`, balance > 0, same currency. Single invoices and (bonus) subsets of up to 4 open invoices of the identified payer.
6. **Amount signal:** exact balance > exact (balance − 10 % TDS on subtotal, INR only) > subset sum > declared/instalment partial > other partial; over-payment excludes the candidate. Exact integer minor-unit comparison, no fee tolerance (policy: international customers pay their own charges).
7. **Date signal:** before invoice date = strong penalty; within terms = small bonus; very late = small penalty.
8. **Score 0–100** = additive points (payer ≤45, amount ≤40, invoice no. ≤25, date ±), minus penalties (unrecognised payer, number belongs to someone else, ambiguity when runner-up is within 10 points → oldest-due first).
9. **Bands:** ≥85 high, 65–84 medium, 40–64 low, <40 **No match** (top-3 alternatives still listed).
10. Reason string assembled from the signals actually used.

## Collections agent
Reminders: one email per customer listing all overdue invoices (balance, currency, due date from DB via templates); not resent within `REMINDER_INTERVAL_DAYS`; scheduled runs only within the policy's working hours. Replies: dedupe by Message-ID, thread by In-Reply-To/References then sender email, unknown sender → Needs attention with nothing shared. LLM only classifies + writes wording; code builds the facts block, enforces routing rules and validates every invoice number/amount/date/bank detail before anything is sent.
