from datetime import date

import pytest

from app.core.money import to_minor
from app.services.matching.engine import THRESHOLD_NO_MATCH, MatchingEngine, Txn, band_for
from app.services.matching.normalize import extract_features, extract_invoice_numbers, name_tokens
from app.services.matching.payer import PayerMatcher, token_similarity
from app.services.matching.signals import amount_signal, date_signal, tds_expected


@pytest.fixture
def engine(customers, invoices):
    return MatchingEngine(customers, invoices)


def inv_by(invoices, number):
    return next(i for i in invoices if i.invoice_number == number)


# ---------------------------------------------------------------- normalisation
@pytest.mark.parametrize(
    "text,expected",
    [
        ("IMPS/KESTREL FOODS/INV 1004", [1004]),
        ("SWIFT CR HARBOUR ANALYTICS INC INV1021", [1021]),
        ("NEFT CR-BRIGHTLINE LOGISTICS PVT LTD-INV-1002", [1002]),
        ("NEFT inv/1027 x", [1027]),
        ("INVOICE NO. 1010, 1011 & 1012", [1010, 1011, 1012]),
        ("INV 1010/1011", [1010, 1011]),
        ("NO NUMBER HERE 2026", []),
    ],
)
def test_invoice_number_extraction(text, expected):
    assert extract_invoice_numbers(text.upper()) == expected


def test_features_strip_noise_and_suffixes():
    f = extract_features("RTGS CR-QUILLON TECH PVT LTD")
    assert f.payer_tokens == ["QUILLON", "TECH"]
    f = extract_features("SEPA CR NORDLYS RETAIL GMBH RE 1024")
    assert f.payer_tokens == ["NORDLYS", "RETAIL"] and f.bare_numbers == [1024]
    assert extract_features("UPI/ORBIS PKG/PART PAYMENT").partial_hint
    assert extract_features("INT.PD:01-10-2026 TO 31-10-2026").bank_entry
    assert extract_features("IMPS/R K SHARMA/CLINIC DUES").payer_tokens == ["SHARMA", "CLINIC"]


def test_name_tokens():
    assert name_tokens("Kestrel Foods Private Limited") == ["KESTREL", "FOODS"]
    assert name_tokens("Nordlys Retail GmbH") == ["NORDLYS", "RETAIL"]


# --------------------------------------------------------------------- payer
@pytest.mark.parametrize(
    "n,c,minimum",
    [("TECH", "TECHNOLOGIES", 0.9), ("PKG", "PACKAGING", 0.8), ("BRIGHTLN", "BRIGHTLINE", 0.8),
     ("KESTRAL", "KESTREL", 0.88), ("CLINIC", "CLINICS", 0.88), ("KESTRELFOODS", "KESTREL", 0.85)],
)
def test_token_similarity_tolerates_variants(n, c, minimum):
    assert token_similarity(n, c) >= minimum


def test_token_similarity_rejects_unrelated():
    assert token_similarity("MAPLE", "NORDLYS") == 0.0
    assert token_similarity("SHARMA", "REDWOOD") == 0.0


def test_payer_identification(customers):
    pm = PayerMatcher(customers)
    for narration, cid in [("NEFT CR-REDWOOD CLINIC", "C006"), ("UPI/ORBIS PKG", "C005"),
                           ("NEFT CR-SAFFRON PEAK HOSP-OCT DUES", "C004")]:
        top = pm.identify(pm.score_all(extract_features(narration).payer_tokens))
        assert top is not None and top.customer_id == cid


def test_generic_words_never_identify_a_payer(customers):
    pm = PayerMatcher(customers)
    for narration in ["NEFT CR-MAPLE RETAIL SERVICES", "IMPS/R K SHARMA/CLINIC DUES", "NEFT CR-GLOBAL MEDIA"]:
        scores = pm.score_all(extract_features(narration).payer_tokens)
        assert pm.identify(scores) is None
        assert not scores[0].anchored


# ------------------------------------------------------------- amount/date
def test_amount_signals(invoices):
    i1007 = inv_by(invoices, "INV-1007")
    assert amount_signal(to_minor(354000), i1007, False).kind == "balance"
    tds = amount_signal(to_minor(324000), i1007, False)
    assert tds.kind == "tds" and tds.tds_minor == to_minor(30000)
    assert amount_signal(to_minor(400000), i1007, False).kind == "over"
    assert amount_signal(to_minor(100000), i1007, False).kind == "partial"
    assert amount_signal(to_minor(100000), i1007, True).kind == "partial_declared"
    i1023 = inv_by(invoices, "INV-1023")  # USD 6000, 2000 already paid
    assert amount_signal(to_minor(2000), i1023, False).kind == "instalment"


def test_tds_only_for_inr_and_untouched_invoices(invoices):
    assert tds_expected(inv_by(invoices, "INV-1007")) == to_minor(30000)
    assert tds_expected(inv_by(invoices, "INV-1021")) == 0  # USD
    assert tds_expected(inv_by(invoices, "INV-1023")) == 0  # USD + part paid
    # Discounted invoice: TDS is on the subtotal per policy
    assert tds_expected(inv_by(invoices, "INV-1012")) == to_minor(6500)


def test_date_signal(invoices):
    inv = inv_by(invoices, "INV-1014")  # invoice date 2026-11-01
    assert date_signal(date(2026, 9, 10), inv).points < -30
    assert date_signal(date(2026, 11, 3), inv).points > 0


# ------------------------------------------------------------ combination
def test_number_payer_amount_all_agree_is_high(engine):
    r = engine.match(Txn(date(2026, 9, 5), "IMPS/KESTREL FOODS/INV 1004", to_minor(59000), "INR"))
    assert r.status == "suggested" and r.allocations[0].invoice_number == "INV-1004"
    assert r.score >= 95 and r.band == "high"
    assert "INV-1004 named" in r.reason


def test_payer_plus_exact_amount_is_80s(engine):
    r = engine.match(Txn(date(2026, 10, 2), "NEFT CR-REDWOOD CLINIC", to_minor(59000), "INR"))
    assert r.allocations[0].invoice_number == "INV-1016"
    assert 80 <= r.score < 95


def test_tds_suggestion_carries_tds(engine):
    r = engine.match(Txn(date(2026, 9, 21), "RTGS CR-QUILLON TECH PVT LTD", to_minor(324000), "INR"))
    assert r.allocations[0].invoice_number == "INV-1007"
    assert r.allocations[0].tds_minor == to_minor(30000)
    assert "TDS" in r.reason


def test_equal_amounts_are_ambiguous_oldest_first(engine):
    r = engine.match(Txn(date(2026, 10, 25), "NEFT CR-KESTREL FOODS", to_minor(59000), "INR"))
    assert r.allocations[0].invoice_number == "INV-1004"
    assert r.band != "high" and "ambiguous" in r.reason
    assert r.signals["ambiguous"]
    assert r.alternatives[0]["invoice_numbers"] == ["INV-1005"]


def test_currency_mismatch_never_matches(engine):
    r = engine.match(Txn(date(2026, 10, 20), "SWIFT CR HARBOUR ANALYTICS INV1022", to_minor(4800), "EUR"))
    assert r.status == "no_match"


def test_unknown_payer_amount_only_is_not_forced(engine):
    r = engine.match(Txn(date(2026, 10, 20), "IMPS/R K SHARMA/CLINIC DUES", to_minor(88500), "INR"))
    assert r.status == "no_match" and r.score < THRESHOLD_NO_MATCH
    assert r.alternatives and r.alternatives[0]["invoice_numbers"] == ["INV-1017"]


def test_drafts_and_paid_never_candidates(engine):
    # INV-1006 (draft, 147500) and INV-1020 (paid, 29500) belong to Kestrel
    for amount, num in [(147500, "INV-1006"), (29500, "INV-1020")]:
        r = engine.match(Txn(date(2026, 10, 20), f"NEFT CR KESTREL FOODS {num}", to_minor(amount), "INR"))
        assert r.status == "no_match"


def test_subset_sum_group(engine):
    r = engine.match(Txn(date(2026, 10, 12), "NEFT CR-SAFFRON PEAK HOSP-OCT DUES", to_minor(194700), "INR"))
    assert sorted(a.invoice_number for a in r.allocations) == ["INV-1010", "INV-1011", "INV-1012"]
    assert sum(a.amount_minor for a in r.allocations) == to_minor(194700)


def test_debits_ignored(engine):
    r = engine.match(Txn(date(2026, 10, 5), "NEFT DR-OFFICE RENT OCT", to_minor(185000), "INR", "debit"))
    assert r.status == "ignored"


def test_competing_rows_lower_confidence(engine):
    t = Txn(date(2026, 10, 2), "NEFT CR-REDWOOD CLINIC", to_minor(59000), "INR")
    first, second = engine.match_many([t, t])
    assert first.status == "suggested"
    assert second.score < first.score and "also suggested" in second.reason


def test_bands():
    assert band_for(90) == "high" and band_for(70) == "medium" and band_for(45) == "low" and band_for(10) == "none"


def test_eval_script_zero_wrong():
    from scripts.eval_matching import evaluate

    s = evaluate()["summary"]
    assert s["wrong"] == 0 and s["band_violations"] == 0
    assert s["recall"] >= 0.9
