"""
backend/utils/json_parser.py
----------------------------
Robuuste JSON-parsing voor LLM-responses.

LLMs produceren regelmatig output die *bijna* JSON is:
  - omsloten door ```json ... ``` markdown fences
  - voorafgegaan door uitleg ("Hier is je JSON:")
  - met een trailing comma
  - met smart quotes
  - met een afgekapte tail (bij token-limit)

Deze module probeert in een vaste volgorde van strategieën:

  1. Direct ``json.loads``.
  2. Strip markdown code fences (```json``` of ```...```).
  3. Vind het eerste ``{`` en de daarbij behorende sluitende ``}`` via
     brace-balancing (slim genoeg om strings/escapes te negeren).
  4. Repareer trailing commas en smart quotes.
  5. Geef op — caller kan een AI-retry triggeren met een herformuleer-prompt.

Validatie tegen een Pydantic-model is een aparte stap zodat je in tests de
parser geïsoleerd kunt valideren.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


T = TypeVar("T", bound=BaseModel)


class JSONParseError(Exception):
    """Wordt geworpen als zelfs na alle reparatie-pogingen geen geldig JSON ontstaat."""

    def __init__(self, message: str, raw: str, attempted: list[str]):
        super().__init__(message)
        self.raw = raw
        self.attempted = attempted


# ---------------------------------------------------------------------------
# Stap 1: markdown-fences strippen
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?", re.MULTILINE)
_TRAILING_FENCE_RE = re.compile(r"\n?```\s*$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    text = _FENCE_RE.sub("", text, count=1)
    text = _TRAILING_FENCE_RE.sub("", text, count=1)
    return text.strip()


# ---------------------------------------------------------------------------
# Stap 2: brace-balancing om het eerste volledige JSON-object te vinden
# ---------------------------------------------------------------------------

def _extract_first_object(text: str) -> str | None:
    """
    Vindt het eerste ``{...}``-blok met gebalanceerde haakjes,
    rekening houdend met strings en escapes.

    Returns het substring of ``None`` als niets gevonden is.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None  # unbalanced


# ---------------------------------------------------------------------------
# Stap 3: lichte repair (trailing commas, smart quotes)
# ---------------------------------------------------------------------------

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_SMART_QUOTES = {
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
}


def _repair(text: str) -> str:
    for smart, plain in _SMART_QUOTES.items():
        text = text.replace(smart, plain)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Hoofdfunctie: parse_robust
# ---------------------------------------------------------------------------

def parse_robust(text: str) -> dict[str, Any]:
    """
    Probeert ``text`` te parsen als een JSON-object.

    Raises
    ------
    JSONParseError
        Als geen enkele strategie een dict oplevert.
    """
    attempts: list[str] = []
    if not text or not text.strip():
        raise JSONParseError("Lege response.", text or "", attempts)

    # Strategie 1: direct
    try:
        attempts.append("direct")
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategie 2: fences strippen
    stripped = _strip_fences(text)
    try:
        attempts.append("strip_fences")
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategie 3: brace-balanced extractie
    extracted = _extract_first_object(stripped)
    if extracted:
        try:
            attempts.append("brace_balance")
            result = json.loads(extracted)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            # Strategie 4: repair + retry
            try:
                attempts.append("repair")
                repaired = _repair(extracted)
                result = json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    # Laatste redmiddel: repair op de hele stripped tekst
    try:
        attempts.append("repair_full")
        result = json.loads(_repair(stripped))
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    snippet = (text[:300] + "…") if len(text) > 300 else text
    logger.warning("JSON-parse mislukt na %s. Snippet: %r", attempts, snippet)
    raise JSONParseError(
        f"Kon geen geldig JSON-object extraheren (strategieën: {attempts}).",
        raw=text,
        attempted=attempts,
    )


# ---------------------------------------------------------------------------
# Validatie tegen een Pydantic-model
# ---------------------------------------------------------------------------

def parse_and_validate(text: str, model: Type[T]) -> T:
    """
    Parse ``text`` en valideer tegen het opgegeven Pydantic-model.

    Raises
    ------
    JSONParseError
        Bij parse-fouten.
    pydantic.ValidationError
        Als de structuur niet aan het schema voldoet.
    """
    data = parse_robust(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        logger.warning("Pydantic-validatie mislukt: %s", exc.errors()[:3])
        raise


# ---------------------------------------------------------------------------
# Helper: bouw een herformuleer-prompt voor de AI
# ---------------------------------------------------------------------------

def build_retry_prompt(previous_response: str, schema_hint: str) -> str:
    """
    Genereert een korte, dwingende prompt die de AI vraagt zijn vorige
    output opnieuw te formatteren als geldig JSON.
    """
    snippet = previous_response.strip()[:500]
    return (
        "Je vorige antwoord was geen geldig JSON-object. "
        "Geef nu UITSLUITEND één JSON-object terug dat exact overeenkomt met dit schema, "
        "zonder begeleidende tekst, zonder markdown-codeblokken, zonder uitleg.\n\n"
        f"Schema:\n{schema_hint}\n\n"
        f"Je vorige (foutieve) antwoord begon met:\n{snippet}\n\n"
        "Antwoord nu uitsluitend met het JSON-object."
    )
