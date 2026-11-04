export type Currency = "INR" | "USD" | "EUR" | "GBP";

export interface Organization {
  name: string;
  address: string;
  accounts_contact_name: string;
  accounts_email: string;
  phone: string;
  default_currency: string;
  accepted_currencies: string[];
  payment_terms: string;
  payment_methods: string[];
  bank_details: { account_name: string; account_number: string; bank: string; ifsc?: string; swift_code?: string };
  policies: Record<string, string>;
}

export interface Customer {
  customer_id: string;
  name: string;
  contact_name: string;
  contact_email: string;
  phone?: string;
  city?: string;
  country?: string;
  currency: Currency;
  aliases: string[];
  invoice_count: number;
  open_count: number;
  overdue_count: number;
  outstanding_minor: number;
  outstanding_display: string;
}

export interface Invoice {
  invoice_number: string;
  customer_id: string;
  customer_name: string;
  po_number: string | null;
  invoice_date: string;
  due_date: string;
  payment_terms: string;
  currency: Currency;
  subtotal_minor: number;
  total_minor: number;
  amount_paid_minor: number;
  tds_minor: number;
  balance_minor: number;
  tax_name: string | null;
  status: "draft" | "sent" | "paid";
  overdue: boolean;
  days_overdue: number;
  display: Record<"subtotal" | "discount" | "tax" | "total" | "amount_paid" | "tds" | "balance", string>;
}

export interface InvoiceDetail extends Invoice {
  line_items: { description: string; quantity: string; unit_price_display: string; amount_display: string }[];
  notes: { at: string; kind: string; text: string }[];
  payments: { amount_display: string; tds_display: string; txn_date: string; reference: string; approved_by: string; approved_at: string }[];
}

export interface Message {
  id: string;
  message_id: string;
  direction: "in" | "out";
  kind: string;
  from_addr?: string;
  to_addr?: string;
  subject?: string;
  body_text?: string;
  clean_text?: string;
  category?: string | null;
  confidence?: number;
  action?: string;
  reason?: string;
  auto_sent?: boolean;
  needs_attention?: boolean;
  draft?: string | null;
  created_at: string;
  sent_by?: string;
}

export interface ConversationSummary {
  id: string;
  customer_id: string | null;
  customer_name: string | null;
  subject: string;
  status: "open" | "needs_attention" | "resolved";
  attention_reason: string | null;
  reminder_count: number;
  last_reminder_at: string | null;
  updated_at: string;
  message_count: number;
  last_message: { direction: string; kind: string; category: string | null; at: string; subject: string } | null;
}

export interface ConversationDetail extends ConversationSummary {
  customer_email: string | null;
  notes: { at: string; kind: string; text: string }[];
  messages: Message[];
}

export interface AttentionItem {
  conversation_id: string;
  customer_id: string | null;
  customer_name: string | null;
  reason: string | null;
  message: Message | null;
  updated_at: string;
}

export interface Allocation {
  invoice_number: string;
  customer_id: string;
  amount_minor: number;
  tds_minor: number;
  amount_display: string;
  tds_display?: string;
  balance_minor?: number;
  balance_display?: string;
  status?: string;
  customer_name?: string;
  expected_tds_minor?: number;
  expected_tds_display?: string;
}

export interface Suggestion {
  id: string;
  status: "pending" | "approved" | "rejected";
  match_status: "suggested" | "no_match" | "ignored";
  score: number;
  band: "high" | "medium" | "low" | "none";
  reason: string;
  allocations: Allocation[];
  amount_kind: string | null;
  alternatives: { invoice_numbers: string[]; score: number; reason: string; kind: string }[];
  payer: { customer_id: string; name: string; score: number } | null;
  signals?: { email_hint?: { customer_id: string; said_on: string; excerpt: string; matched: string } };
  applied?: { invoice_number: string; amount_minor: number; tds_minor: number; new_status: string }[];
  approved_by?: string;
  close_with_tds?: boolean;
}

export interface Transaction {
  id: string;
  row_no: number;
  txn_date: string;
  narration: string;
  reference: string;
  amount_minor: number;
  amount_display: string;
  direction: "credit" | "debit";
  currency: Currency;
  status: "suggested" | "unmatched" | "ignored" | "duplicate" | "approved" | "rejected" | "applying";
}

export interface Statement {
  id: string;
  filename: string;
  uploaded_at: string;
  uploaded_by: string;
  row_count: number;
  credit_count: number;
  suggested_count: number;
  duplicate_count: number;
}

export interface StatementDetail {
  statement: Statement;
  rows: { transaction: Transaction; suggestion: Suggestion | null }[];
}

export interface SystemStatus {
  today: string;
  as_of_date_pinned: boolean;
  smtp_configured: boolean;
  imap_configured: boolean;
  org_email: string;
  llm_provider: string;
  inbox_poll_seconds: number;
  reminder_interval_days: number;
  reminder_schedule_minutes: number;
  last_inbox_poll: string | null;
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  action: string;
  entity: string;
  details: Record<string, unknown>;
}
