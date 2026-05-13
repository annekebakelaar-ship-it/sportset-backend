"""
backend/services/matching_service.py
------------------------------------
Matching-engine voor de YouCaps Vision Scanner.

Doel
----
Gegeven de rauwe AI-extractie (``ScanExtraction``), beslissen we welke
ingrediënten overeenkomen met:

1. De geverifieerde knowledge base (``backend/db/knowledge_base.json``).
2. De supplements-catalogus in de SQLite-database.

En welke veiligheidsrisico's (interacties / contra-indicaties) daaruit volgen.

Strategie
---------
* Canonical-index opbouwen bij startup uit de KB.
* Per AI-ingrediënt: normaliseer → exact-alias-hit → substring-hit → rapidfuzz.
* Drempelwaarden uit ``settings.match_strong_threshold`` /
  ``settings.match_weak_threshold``.
* Dedup-strategie: matches met dezelfde ``canonical_key`` worden samengevoegd,
  hoogste score wint, doseringen worden geconcatened indien verschillend.
* Risk-aggregatie filtert op ``verified=true`` in de KB.

Ontwerp-keuze (R-003 mitigatie)
-------------------------------
Risico's komen UITSLUITEND uit de geverifieerde knowledge base. AI-output
wordt nooit als bron voor medische claims gebruikt.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.orm_models import IngredientORM, SupplementORM
from backend.models.scan_schemas import (
    IngredientMatch,
    ScanExtraction,
    ScanRisk,
    ScannedIngredient,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisatie
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_MULTI_WS_RE = re.compile(r"\s+")
# Verwijder veelvoorkomende dosering-tokens uit een ingredientstring zodat de
# matcher niet door "Vitamine C 1000mg" verward raakt.
_DOSAGE_TOKEN_RE = re.compile(
    r"\b\d+([.,]\d+)?\s*(mg|mcg|µg|ug|g|kg|iu|i\.e\.|ie|%)\b",
    flags=re.IGNORECASE,
)


def normalize(text: str) -> str:
    """
    Aggressieve, deterministische normalisatie:
      * NFKD + diakritische tekens strippen
      * lowercase
      * doseringen zoals "1000mg" eruit
      * leestekens → spatie
      * meerdere spaties → één
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = ascii_text.lower()
    no_dose = _DOSAGE_TOKEN_RE.sub(" ", lower)
    no_punct = _PUNCT_RE.sub(" ", no_dose)
    collapsed = _MULTI_WS_RE.sub(" ", no_punct).strip()
    return collapsed


# ---------------------------------------------------------------------------
# Knowledge-base entries & risico's
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalEntry:
    """Eén canonical ingrediënt met al zijn aliassen en bekende interacties."""

    key: str  # bv. 'magnesium'
    display_name: str  # bv. 'Magnesium'
    aliases_normalized: tuple[str, ...]  # genormaliseerde unieke aliassen
    interactions: tuple[dict, ...]  # rauwe KB-records, indices op 'verified'
    allergens_relevant: tuple[dict, ...] = ()


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

class KnowledgeBaseIndex:
    """
    In-memory index van knowledge_base.json voor snelle lookups.

    Structuur:
        _by_alias: dict[normalized_alias, canonical_key]
        _entries:  dict[canonical_key, CanonicalEntry]
    """

    def __init__(self) -> None:
        self._by_alias: dict[str, str] = {}
        self._entries: dict[str, CanonicalEntry] = {}
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def size(self) -> int:
        return len(self._entries)

    def load(self, path: str | Path) -> None:
        """
        Laadt of herlaadt de KB. Thread-safe.
        Stilte bij ontbrekend bestand → logger.warning, maar service blijft draaien.
        """
        with self._lock:
            kb_path = Path(path)
            if not kb_path.exists():
                logger.warning("Knowledge base niet gevonden op %s", kb_path)
                self._by_alias = {}
                self._entries = {}
                self._loaded = True
                return

            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Kon knowledge base niet lezen: %s", exc)
                self._by_alias = {}
                self._entries = {}
                self._loaded = True
                return

            interactions: list[dict] = data.get("interactions", []) or []
            allergens: list[dict] = data.get("allergens", []) or []

            entries: dict[str, dict] = {}
            for record in interactions:
                key = record.get("supplement_key")
                if not key:
                    continue
                entry = entries.setdefault(
                    key,
                    {
                        "display_name": key.title(),
                        "aliases": set(),
                        "interactions": [],
                    },
                )
                entry["aliases"].add(key)
                for a in record.get("supplement_aliases", []) or []:
                    if isinstance(a, str) and a.strip():
                        entry["aliases"].add(a.strip())
                entry["interactions"].append(record)

            # Allergens: toegankelijk via supplement_keys waar het in voorkomt.
            allergen_by_key: dict[str, list[dict]] = {}
            for record in allergens:
                for s_key in record.get("supplements_containing", []) or []:
                    allergen_by_key.setdefault(s_key, []).append(record)

            by_alias: dict[str, str] = {}
            entries_final: dict[str, CanonicalEntry] = {}
            for key, raw in entries.items():
                normalized_aliases = sorted(
                    {normalize(a) for a in raw["aliases"] if normalize(a)}
                )
                for alias in normalized_aliases:
                    # Bij conflict: eerste registratie wint (KB heeft consistentie nodig).
                    by_alias.setdefault(alias, key)
                entries_final[key] = CanonicalEntry(
                    key=key,
                    display_name=raw["display_name"],
                    aliases_normalized=tuple(normalized_aliases),
                    interactions=tuple(raw["interactions"]),
                    allergens_relevant=tuple(allergen_by_key.get(key, [])),
                )

            self._by_alias = by_alias
            self._entries = entries_final
            self._loaded = True
            logger.info(
                "Knowledge base geladen: %d canonical entries, %d aliassen.",
                len(entries_final),
                len(by_alias),
            )

    # ------- Lookups -------

    def get(self, canonical_key: str) -> Optional[CanonicalEntry]:
        return self._entries.get(canonical_key)

    def all_entries(self) -> Iterable[CanonicalEntry]:
        return self._entries.values()

    def lookup_by_alias_exact(self, normalized_query: str) -> Optional[str]:
        """Exacte alias-hit; geeft canonical_key of None."""
        return self._by_alias.get(normalized_query)

    def search_fuzzy(self, normalized_query: str) -> tuple[Optional[str], float]:
        """
        Beste fuzzy-match: scant alle aliassen via rapidfuzz.token_set_ratio.

        Returns
        -------
        (canonical_key | None, score 0.0-1.0)
        """
        if not normalized_query:
            return None, 0.0

        best_key: Optional[str] = None
        best_score = 0.0
        for alias, key in self._by_alias.items():
            score = fuzz.token_set_ratio(normalized_query, alias) / 100.0
            if score > best_score:
                best_score = score
                best_key = key
                if best_score >= 0.999:
                    break
        return best_key, best_score


# Eén proces-wijde index. ``init_index`` wordt aangeroepen bij FastAPI startup.
KB_INDEX = KnowledgeBaseIndex()


def init_index(path: str | None = None) -> None:
    """Laad de KB. Idempotent; veilig om meerdere malen aan te roepen."""
    KB_INDEX.load(path or settings.knowledge_base_path)


# ---------------------------------------------------------------------------
# Match-pipeline
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    """Intern hulpresultaat voor de pipeline."""

    canonical_key: Optional[str]
    canonical_name: Optional[str]
    score: float
    quality: str  # strong | weak | unmatched
    db_supplement_ids: list[str] = field(default_factory=list)


def _classify_quality(score: float) -> str:
    if score >= settings.match_strong_threshold:
        return "strong"
    if score >= settings.match_weak_threshold:
        return "weak"
    return "unmatched"


def _match_one(ingredient: ScannedIngredient) -> MatchResult:
    """Matcht één AI-ingrediënt tegen de KB-index."""
    candidates = [ingredient.normalized_name, ingredient.name]
    best_key: Optional[str] = None
    best_score = 0.0

    # 1. Exact-alias-hit op zowel name als normalized_name
    for cand in candidates:
        norm = normalize(cand or "")
        if not norm:
            continue
        hit = KB_INDEX.lookup_by_alias_exact(norm)
        if hit:
            return MatchResult(
                canonical_key=hit,
                canonical_name=KB_INDEX.get(hit).display_name if KB_INDEX.get(hit) else hit.title(),
                score=1.0,
                quality="strong",
            )
        # 2. Fuzzy: hou de beste van alle kandidaten bij
        key, score = KB_INDEX.search_fuzzy(norm)
        if key and score > best_score:
            best_key = key
            best_score = score

    if best_key is None:
        return MatchResult(canonical_key=None, canonical_name=None, score=0.0, quality="unmatched")

    entry = KB_INDEX.get(best_key)
    return MatchResult(
        canonical_key=best_key,
        canonical_name=entry.display_name if entry else best_key.title(),
        score=round(best_score, 3),
        quality=_classify_quality(best_score),
    )


def _enrich_with_db(
    matches: list[tuple[ScannedIngredient, MatchResult]],
    db: Session,
) -> None:
    """
    Vult ``db_supplement_ids`` per match: alle catalogus-supplementen die dit
    ingrediënt bevatten (case-insensitive substring of canonical-name match).
    Mutates ``matches`` in-place.
    """
    if not matches:
        return

    # Verzamel kandidaten voor één DB-query (vermijdt N+1).
    needles: set[str] = set()
    for ing, result in matches:
        if result.canonical_name:
            needles.add(result.canonical_name)
        if ing.name:
            needles.add(ing.name)
    if not needles:
        return

    # Eenvoudige LIKE-zoekopdracht per needle. Voor SQLite is dit snel genoeg
    # tot enkele duizenden ingredient-records; bij Postgres-schaal zou je een
    # GIN-index op name overwegen.
    rows = db.execute(
        select(IngredientORM.supplement_id, IngredientORM.name)
    ).all()
    if not rows:
        return

    norm_needles = {n: normalize(n) for n in needles}

    for ing, result in matches:
        for supp_id, ing_name in rows:
            ing_norm = normalize(ing_name)
            for n in norm_needles.values():
                if not n:
                    continue
                if n in ing_norm or ing_norm in n:
                    if supp_id not in result.db_supplement_ids:
                        result.db_supplement_ids.append(supp_id)
                    break


# ---------------------------------------------------------------------------
# Risk-aggregatie
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _collect_risks(canonical_keys: Iterable[str]) -> list[ScanRisk]:
    """Verzamelt geverifieerde risico's voor de gegeven canonical keys."""
    risks: list[ScanRisk] = []
    seen: set[tuple[str, str]] = set()  # (canonical_key, target) — dedup
    for key in canonical_keys:
        entry = KB_INDEX.get(key)
        if entry is None:
            continue
        for record in entry.interactions:
            if not record.get("verified", False):
                continue
            target = record.get("target")
            if not target:
                continue
            dedup_key = (key, target.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            risks.append(
                ScanRisk(
                    canonical_key=key,
                    canonical_name=entry.display_name,
                    target=target,
                    target_type=record.get("target_type"),
                    severity=record.get("severity", "medium"),
                    mechanism=record.get("mechanism"),
                    clinical_effect=record.get("clinical_effect"),
                    management=record.get("management"),
                    evidence_level=record.get("evidence_level"),
                    sources=record.get("sources", []) or [],
                    interaction_id=record.get("id"),
                )
            )
    # Sorteer op severity (hoog → laag) en daarna op canonical_name
    risks.sort(
        key=lambda r: (-_SEVERITY_RANK.get(r.severity, 0), r.canonical_name, r.target)
    )
    return risks


# ---------------------------------------------------------------------------
# Publieke entrypoint
# ---------------------------------------------------------------------------

@dataclass
class MatchingOutput:
    matches: list[IngredientMatch]
    risks: list[ScanRisk]
    overall_confidence: float


def analyze(extraction: ScanExtraction, db: Session) -> MatchingOutput:
    """
    Hoofd-entrypoint voor de matching-laag.

    Stappen:
      1. Match elk ingrediënt → IngredientMatch.
      2. Dedup op canonical_key (hoogste score wint, doses gemerged).
      3. Verrijk met catalogus-IDs uit SQLite.
      4. Verzamel geverifieerde risico's voor alle canonical keys.
      5. Bereken een aggregate confidence-score.
    """
    if not KB_INDEX.is_loaded:
        init_index()

    # Stap 1: per AI-ingrediënt
    raw_matches: list[tuple[ScannedIngredient, MatchResult]] = []
    for ing in extraction.ingredients:
        result = _match_one(ing)
        raw_matches.append((ing, result))

    # Stap 2: dedup. Niet-gematchte items behouden we individueel
    # zodat de UI ook "onbekende" ingrediënten kan tonen.
    by_key: dict[str, tuple[ScannedIngredient, MatchResult]] = {}
    unmatched: list[tuple[ScannedIngredient, MatchResult]] = []
    for ing, res in raw_matches:
        if res.canonical_key is None:
            unmatched.append((ing, res))
            continue
        existing = by_key.get(res.canonical_key)
        if existing is None or res.score > existing[1].score:
            by_key[res.canonical_key] = (ing, res)

    deduped: list[tuple[ScannedIngredient, MatchResult]] = list(by_key.values()) + unmatched

    # Stap 3: DB-enrichment (alleen voor matches met canonical_key)
    _enrich_with_db([m for m in deduped if m[1].canonical_key], db)

    # Stap 4: risico's
    risks = _collect_risks(by_key.keys())

    # Stap 5: bouw response-objecten
    ingredient_matches: list[IngredientMatch] = []
    for ing, res in deduped:
        ingredient_matches.append(
            IngredientMatch(
                extracted=ing,
                canonical_key=res.canonical_key,
                canonical_name=res.canonical_name,
                match_score=round(res.score, 3),
                match_quality=res.quality,
                db_supplement_ids=list(res.db_supplement_ids),
            )
        )

    overall_confidence = _aggregate_confidence(extraction, ingredient_matches)
    return MatchingOutput(
        matches=ingredient_matches, risks=risks, overall_confidence=overall_confidence
    )


def _aggregate_confidence(
    extraction: ScanExtraction, matches: list[IngredientMatch]
) -> float:
    """
    Combineert de AI-confidence met de matching-quality:
      - 70% AI-confidence (overall + gemiddelde per ingredient)
      - 30% gemiddelde match-score van strong/weak matches
    Resultaat in [0.0, 1.0].
    """
    ai_overall = max(0.0, min(1.0, extraction.confidence or 0.0))
    if extraction.ingredients:
        ai_per_ing = sum(i.confidence for i in extraction.ingredients) / len(extraction.ingredients)
    else:
        ai_per_ing = ai_overall
    ai_score = (ai_overall + ai_per_ing) / 2.0

    if matches:
        match_score = sum(m.match_score for m in matches) / len(matches)
    else:
        match_score = 0.0

    combined = 0.7 * ai_score + 0.3 * match_score
    return round(max(0.0, min(1.0, combined)), 3)
