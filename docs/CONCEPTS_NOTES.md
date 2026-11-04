# Concepts notes: billing, AR and revenue recognition

Interview study sheet for the AcmeCorp collections and reconciliation app. Sources are listed at the end. Anything marked "(vendor)" is how Stripe or Sequence model it, which is not always the same as the accounting standard.

---

## 1. Revenue recognition basics

**Accrual vs cash**
- Cash basis: revenue is booked when money arrives. It is simple, but it is not GAAP/IFRS for companies of any size.
- Accrual basis: revenue is booked when it is *earned*, meaning a performance obligation is satisfied, whatever the billing or payment date. Billing, cash and revenue are three separate timelines.

**Balance sheet accounts that sit between billing and revenue**

| Account | Type | Meaning |
|---|---|---|
| Accounts receivable (AR) | Asset | An unconditional right to consideration: only the passage of time is needed. It is usually created when an invoice is issued/finalised. |
| Deferred revenue (contract liability) | Liability | Billed or collected, but not yet earned. Example: an annual licence billed upfront. |
| Unbilled receivable / unbilled revenue (approximately a contract asset) | Asset | Earned, but not yet invoiced. Example: usage in arrears, or the last month before a quarterly bill. Strictly, a contract asset is a right that depends on something other than time, while an unbilled receivable is unconditional. Vendors blur the two. |
| Tax liability (GST/VAT/sales tax payable) | Liability | Tax collected on behalf of the government. It is never revenue. |

**ASC 606 / IFRS 15 five steps**
1. Identify the contract.
2. Identify the performance obligations (POs). A PO is a distinct promised good or service: the customer can benefit from it on its own, and it is separately identifiable within the contract.
3. Determine the transaction price. This includes variable consideration such as usage, rebates and discounts, subject to the constraint that you do not book amounts likely to reverse. Tax collected for authorities is excluded.
4. Allocate the price to the POs in proportion to standalone selling price (SSP). If a bundle is discounted, the discount is spread across the POs by SSP unless it clearly belongs to one of them.
5. Recognise revenue when, or as, each PO is satisfied.

**Point in time vs over time**
- Over time applies if any one of these holds: the customer receives and consumes the benefit as you perform (SaaS, support); your work enhances an asset the customer controls; or the asset has no alternative use to you and you have an enforceable right to payment for work done so far.
- Over-time methods:
  - Ratable / straight-line, for stand-ready subscriptions.
  - Usage-based, where revenue follows consumption. A practical expedient lets you recognise the amount you have the right to invoice when that amount matches the value delivered.
  - Milestones or input measures, for projects.
- Point in time: setup fees that are not a distinct ongoing service, one-off deliverables, and goods on transfer of control. Whether an implementation fee is a separate PO is a judgement call.

**Worked example (INR, matches the app's GST context)**

A 12-month licence for ₹12,00,000, plus 18% GST, invoiced upfront on 1 April.

| Date | Debit | Credit | Amount |
|---|---|---|---|
| 1 Apr (invoice) | AR | Deferred revenue | 12,00,000 |
| 1 Apr | AR | GST payable | 2,16,000 |
| End of each month | Deferred revenue | Revenue | 1,00,000 |
| On receipt | Bank | AR | 14,16,000 |

- At 30 June: revenue recognised = ₹3,00,000, deferred revenue = ₹9,00,000, and the GST liability is unaffected by recognition.
- If the same licence were billed quarterly in arrears, each month would instead post Dr Unbilled AR / Cr Revenue ₹1,00,000. At the quarter-end invoice the entry is Dr AR / Cr Unbilled AR.

---

## 2. Contracts, schedules, phases, renewals, amendments

- **Contract vs invoice.** The contract (or order form/quote) defines the price and the POs. A **billing schedule** turns it into dated invoices. Revenue follows delivery, not the schedule.
- **Billing type.** In-advance invoices at the start of a period and creates deferred revenue. In-arrears invoices at the end of a period and creates unbilled revenue first.
- **Phases** (Sequence's term) are sequential, non-overlapping periods inside one schedule that carry different prices. Uses: trials, ramps (for example +25% a year), renewals and co-termed upsells. Phases change *price*, not *invoice timing*, unless you reset the billing day.
- **Proration.** A mid-period change produces partial periods charged pro rata by days. Example from Sequence's concepts page: $100/month moving to $250/month on 16 April gives $100 x 15/30 + $250 x 15/30 = $50 + $125 = $175. (The page prints the total as "$75", which looks like a typo.)
- **Renewal.** This is either a new contract or new phases appended to the same schedule. Sequence can append renewal phases and extend the schedule's end date.
- **Contract modification (amendment/upgrade) under ASC 606:**
  - If it adds distinct goods at their SSP, treat it as a separate new contract.
  - If the remaining goods are distinct but not priced at SSP, account for it prospectively: terminate the old contract and allocate the unrecognised remainder plus the new consideration to the remaining POs.
  - If the remaining goods are not distinct (part of a single PO), make a cumulative catch-up adjustment.
- **Cancellation.** In-advance fees are usually refunded or credited pro rata through a credit note. In-arrears fees are prorated on a final invoice. Sequence documents exactly this.
- **Co-terming** means aligning an upsell's end date to the existing contract end so that everything renews together.

---

## 3. Pricing models

| Model | How it charges | Example |
|---|---|---|
| Flat / standard | Fixed recurring or one-time fee | $1,500/month in arrears; $2,500 one-time onboarding |
| Per-seat (linear) | Seats x price | $15/seat/month |
| Per-seat (graduated) | The per-seat rate depends on the tier a seat falls in | First 15 seats at £12, the rest at £15 |
| Usage, linear | Units x rate | $0.10/unit, so 550 units = $55 |
| Usage, percentage | % of an amount, optional min/max per unit | 2% per payment, min $1, cap $10 |
| **Volume tiers** | *All* units are priced at the rate of the tier the total lands in | Tiers 0-100 at $1 + $20, 100+ at $0.75 + $50. 125 units = 125 x 0.75 + 50 = **$143.75** |
| **Graduated tiers** | Each unit is priced at the rate of the tier it falls in, and tiers accumulate (like income tax) | 0-500 at $0.5 + $500, 501+ at $0.7 + $750. 600 units = 250 + 500 + 70 + 750 = **$1,570** |
| Packaged | Price per block of units, rounded up | $10 per 250 units, so 600 units = 3 packages = $30 |
| Minimum commitment / minimum fee | If usage is below the floor, a **true-up** line tops it up to the minimum | Minimum A$100, usage A$20, true-up A$80 |
| Prepaid credits / drawdown | The customer pays upfront for a pool, usage burns it down, and overage is billed once it runs out | $8,000 monthly API credit, refreshed monthly |

**Seats.**
- Billing can be in advance (seat balance at the start of the period) or in arrears (balance at the end).
- A contracted minimum can apply. Example: 100 seats are billed even if 90 are used.
- Overages can be billed at period end or monthly.
- Proration has three options: prorate added seats only, prorate added and removed seats, or no proration.

**Revenue angle.**
- Usage and true-ups are variable consideration. A true-up for a period that has already ended is earned immediately; Sequence uses point-in-time recognition for true-ups.
- Prepaid credits are normally a contract liability until consumed.
- Unused credits that are expected to expire ("breakage") are recognised in proportion to usage, or once use becomes remote.
- **Vendor caveat:** Sequence's credit-grant page says a grant "carries revenue that has already been recognized when the grant was issued" and that consumption is not double counted. This is their modelling choice. In an interview, give the standard answer (liability until used) and mention that the vendor differs.

---

## 4. Invoicing lifecycle, terms, dunning, ageing

| Stripe status | Sequence status | Notes |
|---|---|---|
| draft | Upcoming -> Draft | Editable. Never chased, never in AR. |
| open (finalised) | Final / Sent | Immutable. Creates AR. Corrections go through a credit note, or void and reissue. |
| open, with a "Past due" badge | Unpaid (payment status) | Stripe keeps the status `open`; past due is a badge. Overdue is derived, not stored. |
| open, after a partial payment | Partially paid | The balance remains. |
| paid | Paid | Stripe can move it back to open by unapplying payments. |
| void | Void | Terminal. Kept for the audit trail, with zero value. Use it for an invoice raised in error. |
| uncollectible | Uncollectible | Bad debt. A Stripe invoice can still be paid later (recovery). |

- **Payment terms.** Net 30 means due 30 days after the invoice date. Sequence lets you anchor the due date to either the accounting date or the issue date. Terms set on a schedule override account defaults.
- **Overdue** = finalised/sent AND balance > 0 AND today > due date. It is computed on read, so it can never be stale.
- **Dunning** is a sequence of reminders before and after the due date. It stops automatically when the invoice is paid, voided or written off, and it escalates for larger amounts.
- **AR ageing** buckets open balances by days past due: current, 1-30, 31-60, 61-90 and 90+. It is used for collections priority and for the bad-debt (expected credit loss) allowance. A partially paid invoice is aged on its *remaining* balance from its original due date.

---

## 5. Credit notes vs refunds vs write-offs vs discounts

| Item | What it is | Revenue | AR | Cash | Tax liability |
|---|---|---|---|---|---|
| **Credit note** | A document that reduces a finalised invoice (overcharge, service failure, post-sale concession) | Reduced: deferred first or pro rata, depending on the vendor mode | Reduced, if the invoice is unpaid | None, unless it is refunded | Reduced pro rata. The GST/VAT on the credited amount is reversed. |
| **Refund** | Cash going back to the customer. On an invoice, it usually follows a credit note. | Reduced (contra revenue) for the recognised portion; the deferred portion is cleared | None (already paid) | Reduced | Reduced if paired with a credit note |
| **Write-off / uncollectible** | You give up collecting. The service was delivered; the customer will not pay. | Standard: unchanged, with the loss shown as bad-debt / credit-loss *expense*. Stripe books it as contra revenue (vendor convention). | Reduced to zero | None | Depends on local law. Tax already remitted may be reclaimable under bad-debt relief rules. |
| **Discount** | A price reduction agreed upfront or at invoicing | Lower transaction price. It is either netted, or shown as gross plus contra revenue (a Stripe setting). | Lower amount billed | Lower amount collected | Tax is computed on the discounted value |
| **Void** | Cancels an invoice raised in error | Reversed | Reversed | None | Reversed |

Key line: a **credit note changes what was sold**. A **refund moves cash**. A **write-off changes what you expect to collect**. A **discount changes the price before or at billing**.

---

## 6. Usage metering

- **Events** are raw, immutable records. Each has a type, a customer id/alias, a timestamp, an idempotency id and properties. Sequence recommends sending events at the most granular level and keeping pricing logic out of them.
- **Aggregation** turns events into a metric: COUNT, SUM(property) or UNIQUE(property), with optional filters.
- The **billing period** is selected by the event timestamp, not by when the event arrives.
- **Idempotency and corrections.** Re-sending the same `customerEventId` overrides the earlier event. Sequence voids an event by re-sending it with the alias `VOID`, or by moving it out of all billing periods or setting it to zero. Events cannot be deleted.
- **Late-arriving usage.** While the invoice is upcoming or draft, recalculate it. After it has been issued, correct it with a credit note or a supplementary charge. In Sequence, changes to metrics are not retroactive. Stripe's docs (as read) say only that usage revenue is recognised when invoices finalise or when the period closes, and that "catch-up revenue" puts past-period amounts in the booking month instead of rewriting closed periods.
- **Tier windows.** Graduated tiers can be measured per period, cumulatively, quarterly or annually (a Sequence option). This changes which tier rate applies.

---

## 7. How Stripe and Sequence approach this

### Stripe Revenue Recognition (vendor)
- **What it automates:** a double-entry ledger built from Stripe objects such as invoices, subscriptions, one-off payments, refunds and disputes. Amortisation granularity is a setting: by day (the default), by second, or by month, with first and last month options. The methodology pages also say revenue is "amortised by the second".
- **PO model:** each invoice line item is its own performance obligation. A line with a service period is deferred at finalisation and amortised evenly. A line *without* a period is recognised in full at finalisation. One-off payments are recognised immediately unless you import a service period. Rules can override this by product, customer, line item or credit note, for example to amortise, exclude, treat as a pass-through fee, or treat as tax.
- **Chart of accounts:**
  - Revenue, and contra-revenue accounts for refunds, disputes, credit notes, bad debt, voids and discounts.
  - AR, Unbilled AR, Deferred revenue, Long-term deferred revenue (beyond 12 periods, on by default), Tax liability and Contract asset (revenue contracts).
  - Gains and losses: FX loss, Recoverables.
- **Taxes:** not revenue. A $31 subscription with 10% exclusive tax gives Revenue 31, Cash 34.10, Tax liability 3.10. With inclusive tax, $31 gives Revenue 27.90 and Tax 3.10. Taxes must be set as tax rates, not as line items; otherwise a rule is needed.
- **Credit notes:** reduce AR. They are split between line items in proportion to amount, or applied to a named line. The *recognised* share goes to the contra account "Credit notes" and the *deferred* share is removed from deferred revenue. Example: a 3-month $90 invoice and a $45 credit note on 1 Feb. Revenue is 31 (Jan), 14 (Feb) and 15.50 (Mar), and the CreditNotes contra is 15.50.
- **Refunds and disputes:** contra revenue for the recognised part; the deferred remainder is cleared. Example: a $90 3-month invoice disputed on 1 Feb puts $31 in Disputes and clears $59 of deferred revenue. A won dispute brings back $90 of cash, booked to Recoverables. A "Record refunds separately" setting shows gross revenue plus a contra line.
- **Uncollectible / void:** the recognised part goes to Bad debt or Voids (contra revenue), the deferred part is cleared, and AR is cleared.
- **Payments outside Stripe:** `paid_out_of_band` books an *External asset* instead of Cash.
- **Multi-currency:** revenue is booked at the estimated rate at finalisation, and cash at the actual settlement rate. The difference goes to FX loss. Example: €30 invoiced at 1.20 = $36 and paid at 1.10 = $33 gives FX loss $3. A functional-currency setting translates everything into one currency.
- **Reports:** the revenue waterfall (booked by month vs recognised in later months, with remaining deferred), recognised/deferred/booked charts, trial balance, period summary, income statement, balance sheet, AR ageing, and debits-and-credits (journal entries, with a QuickBooks export). Settings cover accounting-period close and reopen, amortisation granularity, catch-up revenue, recoveries as gains, and discounts as contra revenue.
- **Not covered by the pages read:** whether Stripe performs a full step-4 SSP reallocation across a multi-element contract. The methodology treats lines independently and mentions "revenue contracts" only in passing, so I would not claim it.

### Sequence (vendor)
- **Positioning:** "quote-to-revenue" for B2B. It covers CPQ quotes, billing schedules, invoicing, credit notes, dunning, rev rec journals and ERP sync (Xero, QuickBooks, NetSuite).
- **Billing schedules:**
  - Draft -> upcoming/active -> complete.
  - In-advance or in-arrears per price. Frequencies are monthly, quarterly, semi-annual or annual. Prices with different frequencies can be mixed in one schedule, and invoices are consolidated when dates coincide.
  - A billing-day setting aligns periods and creates prorated first and last periods.
  - Payment terms (Net 30, Net 60 or custom) are set per schedule.
  - In-advance billing is not compatible with usage pricing; use credits instead.
- **Pricing:** standard (fixed recurring or one-time); usage (linear, percentage, volume, graduated, packaged, credit burndown); seats (linear or graduated, minimums, overages, three proration modes); minimum fees with automatic true-ups that can span products; credit-based billing (prepaid grants attached to a phase, scoped to products, refreshed and written off at refresh).
- **Invoicing:**
  - Statuses are Upcoming / Draft / Final / Sent / Void. The payment status (Unpaid / Partially paid / Paid / Uncollectible) is tracked separately.
  - Gapless numbering is assigned on finalisation.
  - Reverse-charge and exempt tax are supported.
  - Sent invoices are corrected by credit note, or by void if unpaid.
- **Dunning:** payment-reminder workflows triggered by "invoice sent", timed relative to the due date. Optional human approval runs through "Watchtower". If a template variable cannot be resolved, the reminder goes to review instead of being sent. Reminders stop automatically when the invoice is paid, voided or uncollectible.
- **AR agent (Labs):** interprets emailed billing requests and prepares changes. *Nothing is applied without human approval.*
- **Rev rec:**
  - States alignment with ASC 606, IFRS 15 and FRS 102.
  - Four accounts: Billed, Recognised, Deferred and Unbilled revenue.
  - Four methods: straight-line (three allocation options for part-months), usage-based (recognised at period end), point-in-time (single-day service periods only) and milestone.
  - Invoice-level discounts are allocated across lines by SSP.
  - Period locking is supported.
  - Reports: monthly journal report, deferred revenue report ("Balance" = remaining obligation; "Remaining" = ties to the GL), and revenue waterfall.
- **Credit notes in rev rec:**
  - *Cancellation mode* (the default) deletes future recognition and reverses deferred revenue first, then recognised revenue only for any excess. Example: a $12,000 annual invoice with $9,000 recognised and $3,000 deferred receives a $6,000 credit note. Deferred is reversed by $3,000 and recognised by $3,000, ending at $6,000 recognised and $6,000 net billed.
  - *Adjustment mode* lets the original invoice keep recognising while the credit note posts mirror entries over its own service period, so that recognised + deferred = net billed at all times.
- **Usage metering:** events -> metrics (COUNT, SUM, UNIQUE) -> price, as described in section 6.

---

## 8. How this relates to my project

**TDS short-payment is not a credit note**
- Invoice ₹3,54,000 = subtotal ₹3,00,000 + GST ₹54,000. The customer deducts TDS at 10% of the subtotal (₹30,000) and pays ₹3,24,000. TDS is computed on the value excluding GST when GST is shown separately.
- The customer has paid that ₹30,000 *to the tax authority on our behalf*. It is our income-tax prepayment, which we claim using the TDS certificate (Form 16A) and verify against Form 26AS. (The applicable section depends on the service, commonly s.194J for professional or technical fees; I would not state it as fact for every customer.)
- Journal: Dr Bank 3,24,000; Dr TDS receivable 30,000; Cr AR 3,54,000.
- Effect: revenue stays ₹3,00,000, the GST liability stays ₹54,000, and the invoice is closed in full. The app records `tds_minor` = 30,000 on the payment allocation.
- Contrast with a ₹30,000 credit note, which reduces both the sale and the tax: Dr Revenue ≈ 25,424; Dr GST payable ≈ 4,576; Cr AR 30,000. Revenue drops, which is wrong for TDS.
- Why a human approves: ₹3,24,000 could be a TDS closure *or* a genuine partial payment, with ₹30,000 still due. Both are plausible, so the suggestion carries a `close_with_tds` choice and a person confirms it. Missing the TDS certificate later is a follow-up item.

**Partial payments**
- The invoice stays open with `balance_minor` > 0 and keeps ageing from its *original* due date. The reminder states the remaining balance, not the total.

**One receipt covering several invoices**
- On approval the receipt is split into allocations across the invoices (the matcher searches subsets of 2 to 5 open invoices of the same payer and currency whose balances sum exactly to the receipt), and each invoice gets its own payment row. This mirrors "cash application" in Stripe (applying one payment to invoices).

**Overdue is computed, never stored**
- Overdue = status `sent` AND balance > 0 AND today > due date. Stripe does the same: the status stays `open` and "Past due" is just a badge.
- Drafts are never chased, because they are not finalised and are not AR.

**"I have paid" emails are not payment**
- An email is a claim, and only bank evidence moves AR. It becomes a note on the conversation and invoice, and the invoice changes only when a bank statement line is matched and approved.
- The claim is still useful *evidence*: if the email quotes a payment reference or invoice number, the matcher adds points to the statement row it points at and shows the email excerpt beside that row.
- Parallel: Stripe's `paid_out_of_band` is a deliberate manual action, and Sequence's AR agent also never writes data without approval.

**Why reconciliation is human-approved**
- Bank narrations are noisy: truncated names, missing invoice numbers, aggregators.
- A wrong match corrupts AR for two customers at once (one shown as paid, the other chased wrongly) and can trigger wrong dunning.
- Approval, an audit log, and alternatives shown with each suggestion are standard controls (segregation of duties, maker-checker).

**GST is a liability, not revenue**
- Revenue = subtotal less discount. Tax goes to GST payable; Stripe and Sequence both exclude tax from revenue.
- TDS is calculated on the subtotal, not on the GST-inclusive total.

**Multi-currency**
- Invoices are in INR, USD, EUR or GBP. The matcher only considers invoices in the *same currency* as the receipt; this is a stated limitation.
- If a USD invoice were settled in INR, a real system would book AR at the invoice-date rate and cash at the receipt rate, posting the difference as a realised FX gain or loss (Stripe's €30: $36 -> $33 example). Unpaid foreign-currency AR is also revalued at period end (an unrealised gain or loss).
- Money is stored as integer minor units to avoid float drift.

**Bank charges on SWIFT receipts**
- Policy: international customers cover their own bank charges. So a USD 5,000 invoice received as USD 4,975 is a **partial payment**: $25 stays open and is chased. The matcher uses exact minor-unit comparison with no fee tolerance.
- Alternative policy, worth being able to defend: absorb small charges with Dr Bank charges (expense) 25 / Cr AR 25, within a tolerance threshold, approved by a human.
- SWIFT charge codes: OUR (sender pays), SHA (shared) and BEN (beneficiary pays). Intermediary banks can still deduct fees even under OUR, so shortfalls happen despite the policy.

---

## 9. Likely interview questions

1. **Why isn't the TDS shortfall a credit note?** Nothing was given back. The customer paid ₹30,000 to the government for us. Revenue and GST are unchanged, and we hold a TDS receivable claimable via Form 16A/26AS. A credit note would wrongly reduce revenue and GST.
2. **Deferred revenue vs unbilled receivable?** Deferred revenue: billed but not yet earned (a liability). Unbilled: earned but not yet billed (an asset, approximately a contract asset).
3. **Annual ₹12L licence billed upfront: what do the P&L and balance sheet show after 3 months?** The P&L shows ₹3L of revenue. The balance sheet shows ₹9L of deferred revenue (a liability) and GST payable of ₹2.16L until it is remitted. Depending on collection, the ₹14.16L billed sits in AR or has moved to cash.
4. **Volume vs graduated tiers?** Volume prices all units at the rate of the final tier. Graduated prices each unit at the rate of its own tier and adds them up.
5. **Credit note vs refund vs write-off?** A credit note reduces the sale (revenue, AR, tax). A refund returns cash. A write-off accepts non-collection: under the standard the revenue stands and a credit loss is booked (Stripe books it as contra revenue).
6. **Why not mark an invoice paid when the customer says "I have paid"?** The email is a claim, not evidence. Cash application needs the bank line. Otherwise AR is overstated and dunning stops wrongly.
7. **Why must reconciliation be human-approved?** The matching is probabilistic, a wrong match damages two customers' balances, TDS vs partial payment is ambiguous, and it is a financial control (maker-checker, with an audit trail).
8. **How do you age a partially paid invoice?** On the remaining balance, from the original due date.
9. **A USD invoice is paid in INR, or arrives $25 short. What happens?** For the FX case, book a realised FX gain or loss between the invoice-date rate and the receipt rate. For the shortfall, the policy treats it as a partial payment that stays open; the alternative is a bank-charge expense write-off within tolerance.
10. **What is a minimum commitment true-up and how is it recognised?** If usage is below the contracted minimum, a true-up line covers the gap. The period has already been delivered, so it is recognised when the shortfall is determined.
11. **Upgrade mid-term: what happens to billing and revenue?** Billing prorates by days (old plan for part of the period, new plan for the rest). Revenue follows the new price from the change date. Under ASC 606 it is treated as a modification (new contract, prospective, or catch-up, depending on distinctness and pricing).
12. **Why compute overdue instead of storing it?** It is a function of time. A stored flag goes stale and needs a job; computing on read is always correct and testable with an injected clock.

---

## Sources read

Stripe (stripe.com/docs/revenue-recognition redirects to docs.stripe.com):
- https://docs.stripe.com/revenue-recognition
- https://docs.stripe.com/revenue-recognition/methodology
- https://docs.stripe.com/revenue-recognition/methodology/subscriptions-and-invoicing (credit notes, tax, uncollectible, void, cash application)
- https://docs.stripe.com/revenue-recognition/methodology/refunds-and-disputes
- https://docs.stripe.com/revenue-recognition/methodology/multi-currency
- https://docs.stripe.com/revenue-recognition/rules
- https://docs.stripe.com/revenue-recognition/revenue-settings
- https://docs.stripe.com/revenue-recognition/reports
- https://docs.stripe.com/revenue-recognition/reports/waterfall
- https://docs.stripe.com/invoicing/overview (invoice statuses, credit notes)

Sequence (index: https://docs.sequencehq.com/llms.txt):
- https://docs.sequencehq.com/billing/billing-concepts
- https://docs.sequencehq.com/billing/billing-schedule-phases
- https://docs.sequencehq.com/billing/create-billing-schedules (payment terms and billing-type sections only)
- https://docs.sequencehq.com/billing/credit-based-billing
- https://docs.sequencehq.com/plans-products/subscription-pricing
- https://docs.sequencehq.com/plans-products/usage-based-pricing
- https://docs.sequencehq.com/plans-products/seat-based-pricing
- https://docs.sequencehq.com/plans-products/minimum-fees
- https://docs.sequencehq.com/invoicing/invoicing-customers
- https://docs.sequencehq.com/invoicing/invoice-discounts
- https://docs.sequencehq.com/invoicing/credit-notes
- https://docs.sequencehq.com/revenue-recognition/overview
- https://docs.sequencehq.com/revenue-recognition/recognition-methods
- https://docs.sequencehq.com/revenue-recognition/credit-notes
- https://docs.sequencehq.com/revenue-recognition/credit-grants
- https://docs.sequencehq.com/revenue-recognition/deferred-revenue
- https://docs.sequencehq.com/revenue-recognition/revenue-waterfall
- https://docs.sequencehq.com/revenue-recognition/use-cases
- https://docs.sequencehq.com/metrics-events/usage-events
- https://docs.sequencehq.com/metrics-events/usage-metrics
- https://docs.sequencehq.com/cpq/renew-contracts
- https://docs.sequencehq.com/agents/payment-reminders
- https://docs.sequencehq.com/agents/ar-agent

The general accounting points (ASC 606 contract-modification rules, breakage, ASC 326 credit losses, Indian TDS and Form 16A/26AS, SWIFT OUR/SHA/BEN) come from general knowledge, not from these vendor pages. Check them against the standard or tax guidance if they are challenged.
