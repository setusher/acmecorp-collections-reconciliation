# Demo video script (about 2 min 45 s)

**Setup before recording:** backend and frontend running; `.env` with the organization Gmail, a Gemini/Groq key, `SEED_CUSTOMER_EMAILS=C002=<customer test inbox>`, `APP_AS_OF_DATE=2026-11-05`; **Reset demo data** clicked. Open four tabs: the app (Invoices), the customer mailbox, `data/bank_statement_sample.csv` in a file picker, and `docs/explanation.pdf` page 1.

---

### 0:00–0:30 · Architecture
*Screen: explanation.pdf, the architecture diagram.*
> "This is AcmeCorp's accounts app. A React UI talks only to a FastAPI backend. The backend is layered: routes, then services, then repositories, then integrations for SMTP, IMAP and the LLM, all on MongoDB. Two rules shape everything. First, every figure a customer sees comes from the database, never from the LLM. Second, nothing financial changes without a human approval. The bank matching engine is plain, deterministic Python. No LLM is involved, so every suggestion can be explained."

### 0:30–0:50 · Invoices and sending a reminder
*Screen: Invoices with the Overdue filter, then Collections → Send reminders.*
> "Overdue is computed, not stored: sent, a balance still unpaid, and past the due date. Today is pinned with APP_AS_OF_DATE so the demo is repeatable. Drafts are never chased. Send reminders sends one email per customer listing all their overdue invoices. Customers still on placeholder addresses are skipped, and clicking again sends nothing, because of the 7-day interval."

### 0:50–1:20 · Reply as a customer, auto-answered
*Screen: customer mailbox → open the reminder → reply:* "Is this the only amount pending from us? Also please send your bank details." *→ app → Check inbox now → Conversations → Kestrel thread.*
> "I'm Arjun from Kestrel Foods, replying to the reminder. Check inbox: the reply threads onto the conversation using In-Reply-To. The LLM only classified it as a balance query and wrote the wording. The invoice list, the ₹1,18,000 total and the bank details were inserted by code. A validator then checked every number, date and bank code against Kestrel's own open invoices before sending. The draft INV-1006 and the paid INV-1020 never appear."
*Show the reply arriving in the customer mailbox.*

### 1:20–1:45 · A risky reply goes to Needs attention
*Screen: reply as the customer:* "We dispute INV-1005, and if this continues our lawyer will get involved." *→ Check inbox now → Needs attention.*
> "Disputes, extension requests and legal language are never answered automatically. A keyword screen in code catches them even if the LLM gets it wrong. Here's the customer's message, why it was flagged, and a safe draft. I edit it and click Send. The human reply is saved in the thread, and reminders pause for this customer while the issue is open."

### 1:45–2:25 · Bank reconciliation: approve a match and a TDS case
*Screen: Bank Reconciliation → Upload `bank_statement_sample.csv`.*
> "I upload the statement. Each receipt gets a suggestion, a 0-to-100 confidence and a one-line reason. Kestrel's row names INV-1004 and matches payer and amount, so it scores 99. Saffron Peak's ₹1,94,700 is exactly three invoices added together. And look at R K Sharma: the amount equals INV-1017 to the rupee, but the payer is unknown, so the app says No match rather than guess. A wrong match is worse than a missed one."
*Approve the Redwood row (INV-1016).*
> "Approving creates a payment and reduces the balance. Now Quillon: ₹3,24,000 against a ₹3,54,000 invoice. That gap is exactly 10% TDS on the ₹3,00,000 subtotal, so 'Close invoice, TDS deducted' is pre-selected."
*Approve, then open INV-1007.*
> "INV-1007 is now paid: ₹3,24,000 cash plus ₹30,000 TDS recorded as a separate component, with the reason in the notes and the audit log."

### 2:25–2:35 · Paid stops chasing
*Screen: Invoices filtered to Redwood; optionally show the audit log.*
*Tick "Ignore reminder interval" → Send reminders → show Redwood's new email.*
> "INV-1016 is paid, so this reminder only lists INV-1017. Every approval, email and reset is in the audit log."

### 2:35–2:50 · What I'd improve
> "Next I would add maker-checker approvals, learn payer aliases from approved matches, run it against more real bank formats, and use an LLM only to explain low-confidence rows, never to decide. The tests cover all of this with a fake LLM and fake mail, and the matching eval scores 37 out of 37 with zero wrong matches."
