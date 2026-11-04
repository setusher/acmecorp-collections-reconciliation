"""Payer identification: which customer does a narration name?

Ensemble (weights in ``WEIGHTS``):

* **anchored token coverage** (main signal): IDF-style weighted share of the
  customer's name tokens found in the narration, with a token similarity that
  tolerates truncation (TECH ~ TECHNOLOGIES, HOSP ~ HOSPITALITY), abbreviations
  by consonant subsequence (PKG ~ PACKAGING, BRIGHTLN ~ BRIGHTLINE), typos
  (Jaro-Winkler) and glued words (KESTRELFOODS). Distinctive tokens weigh 3x
  generic business words.
* **rapidfuzz token_set_ratio**: order-insensitive, ignores extra words.
* **char 3-gram TF-IDF cosine**: robust to truncation / missing spaces.
* **Jaro-Winkler** of the whole cleaned strings: prefix-heavy typo tolerance.
* **token Jaccard**: plain overlap sanity check.

A customer is only *identified* when a distinctive token is matched (the
"anchor"); sharing only generic words such as RETAIL never identifies a payer.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models.domain import Customer
from app.services.matching.normalize import GENERIC_BUSINESS_WORDS, name_tokens

WEIGHTS = {"coverage": 0.55, "token_set": 0.15, "tfidf": 0.15, "jaro_winkler": 0.10, "jaccard": 0.05}
DISTINCTIVE_WEIGHT = 3.0
GENERIC_WEIGHT = 1.0
ANCHOR_MIN_SIM = 0.85
PAYER_MIN_SCORE = 0.60  # minimum ensemble score to call a payer identified
PAYER_MIN_MARGIN = 0.10  # identified payer must beat the runner-up by this much
UNANCHORED_CAP = 0.40


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def token_similarity(n: str, c: str) -> float:
    """Similarity of a narration token ``n`` to a customer-name token ``c`` (0..1)."""
    if n == c:
        return 1.0
    if len(n) >= 3 and c.startswith(n):  # truncation: TECH -> TECHNOLOGIES
        return 0.92
    if len(c) >= 5 and c in n and len(n) > len(c):  # glued words: KESTRELFOODS
        return 0.9
    if len(n) >= 3 and n[0] == c[0] and _is_subsequence(n, c) and len(n) >= 0.3 * len(c):
        return 0.85  # abbreviation: PKG -> PACKAGING, BRIGHTLN -> BRIGHTLINE
    jw = JaroWinkler.similarity(n, c)
    if min(len(n), len(c)) >= 4 and jw >= 0.88:  # typo / plural: KESTRAL, CLINIC(S)
        return round(jw, 3)
    return 0.0


@dataclass
class PayerScore:
    customer_id: str
    name: str
    score: float
    anchored: bool
    components: dict[str, float]
    variant: str


@dataclass
class _Variant:
    customer: Customer
    text: str
    tokens: list[str]
    weights: dict[str, float]


class PayerMatcher:
    def __init__(self, customers: list[Customer]):
        self.customers = customers
        self.variants: list[_Variant] = []
        doc_freq: dict[str, int] = {}
        per_customer_tokens: dict[str, set[str]] = {}
        for c in customers:
            toks: set[str] = set()
            for name in [c.name, *c.aliases]:
                toks.update(name_tokens(name))
            per_customer_tokens[c.customer_id] = toks
            for t in toks:
                doc_freq[t] = doc_freq.get(t, 0) + 1
        for c in customers:
            for name in [c.name, *c.aliases]:
                toks = name_tokens(name)
                if not toks:
                    continue
                weights = {
                    t: (GENERIC_WEIGHT if (t in GENERIC_BUSINESS_WORDS or doc_freq.get(t, 0) > 1) else DISTINCTIVE_WEIGHT)
                    for t in toks
                }
                self.variants.append(_Variant(c, " ".join(toks), toks, weights))
        corpus = [v.text for v in self.variants] or ["X"]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3), lowercase=False)
        self.matrix = self.vectorizer.fit_transform(corpus)

    def _score_variant(self, idx: int, tokens: list[str], text: str, vec) -> PayerScore:
        v = self.variants[idx]
        total_w = sum(v.weights.values())
        covered = 0.0
        anchored = False
        for ct in v.tokens:
            best = max((token_similarity(nt, ct) for nt in tokens), default=0.0)
            covered += v.weights[ct] * best
            if v.weights[ct] == DISTINCTIVE_WEIGHT and best >= ANCHOR_MIN_SIM:
                anchored = True
        coverage = covered / total_w if total_w else 0.0
        comps = {
            "coverage": coverage,
            "token_set": fuzz.token_set_ratio(text, v.text) / 100.0,
            "tfidf": float(cosine_similarity(vec, self.matrix[idx])[0, 0]),
            "jaro_winkler": JaroWinkler.similarity(text, v.text),
            "jaccard": len(set(tokens) & set(v.tokens)) / len(set(tokens) | set(v.tokens)),
        }
        score = sum(WEIGHTS[k] * comps[k] for k in WEIGHTS)
        if not anchored:
            score = min(score, UNANCHORED_CAP)
        return PayerScore(v.customer.customer_id, v.customer.name, round(score, 4), anchored,
                          {k: round(x, 3) for k, x in comps.items()}, v.text)

    def score_all(self, payer_tokens: list[str]) -> list[PayerScore]:
        """Best score per customer, sorted descending."""
        if not payer_tokens or not self.variants:
            return []
        text = " ".join(payer_tokens)
        vec = self.vectorizer.transform([text])
        best: dict[str, PayerScore] = {}
        for i in range(len(self.variants)):
            s = self._score_variant(i, payer_tokens, text, vec)
            if s.customer_id not in best or s.score > best[s.customer_id].score:
                best[s.customer_id] = s
        return sorted(best.values(), key=lambda s: s.score, reverse=True)

    @staticmethod
    def identify(scores: list[PayerScore]) -> PayerScore | None:
        if not scores:
            return None
        top = scores[0]
        runner = scores[1].score if len(scores) > 1 else 0.0
        if top.anchored and top.score >= PAYER_MIN_SCORE and top.score - runner >= PAYER_MIN_MARGIN:
            return top
        return None
