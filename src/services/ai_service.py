"""
backend/services/ai_service.py
------------------------------
Drie kernservices voor de YouCaps Supplements API:

1. AIScanner    – Verwerkt ruwe etikettekst via Claude claude-opus-4-5 naar een
                  gestructureerd Supplement-object.
2. SafetyEngine – Controleert of een supplement conflicteert met
                  medicijnen die de gebruiker gebruikt.
3. AIAdvice     – Genereert persoonlijk advies over een supplement via Claude.

Gemigreerd vanuit: /ai_service.py (kladblok-versie)
Fase: 1 – Discovery (logica overgenomen; refactoring & dependency injection in Fase 2)

TODO (Fase 2):
  - [ ] Vervang globale _client door dependency injection via FastAPI Depends()
  - [ ] Voeg retry-logic toe bij AI-aanroepen (R-05 uit risico-register)
  - [ ] Koppel allergieën uit user_profile aan check_safety() (R-09)
  - [ ] Voeg structured logging toe (R-08)
"""

from __future__ import annotations

import json
import os
import logging
from typing import List

import anthropic
from src.models.schema import (
    Supplement,
    SupplementCreate,
    ContraIndication,
    SafetyCheckResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anthropic client – lazy initialisatie zodat de server ook zonder sleutel
# kan opstarten (fout pas bij eerste API-aanroep).
# ---------------------------------------------------------------------------
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Retourneert de Anthropic-client, aangemaakt bij eerste gebruik."""
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is niet ingesteld. "
                "Voeg deze toe aan het .env bestand in de backend-map."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Fictieve medicijn-database voor de Safety Engine
# TODO (Fase 2): verplaats naar de database (tabel: known_interactions)
# ---------------------------------------------------------------------------
KNOWN_INTERACTIONS: dict[str, List[ContraIndication]] = {
    # Melatonine
    "melatonine": [
        ContraIndication(
            medication_or_condition="Warfarine",
            severity="medium",
            description="Melatonine kan de anticoagulante werking van warfarine versterken.",
        ),
        ContraIndication(
            medication_or_condition="Fluvoxamine",
            severity="high",
            description="Fluvoxamine verhoogt de melatoninespiegel sterk; combinatie vermijden.",
        ),
        ContraIndication(
            medication_or_condition="Benzodiazepinen",
            severity="medium",
            description="Additief sederend effect; verhoogd risico op overmatige slaperigheid.",
        ),
    ],
    # Vitamine K2
    "vitamine k2": [
        ContraIndication(
            medication_or_condition="Warfarine",
            severity="high",
            description="Vitamine K2 antagoniseert direct de werking van warfarine.",
        ),
        ContraIndication(
            medication_or_condition="Acenocoumarol",
            severity="high",
            description="Zelfde mechanisme als warfarine; INR-waarden kunnen sterk dalen.",
        ),
    ],
    # Sint-janskruid
    "sint-janskruid": [
        ContraIndication(
            medication_or_condition="SSRI antidepressiva",
            severity="high",
            description="Risico op serotoninesyndroom bij combinatie met SSRI's.",
        ),
        ContraIndication(
            medication_or_condition="Orale anticonceptiva",
            severity="high",
            description="Vermindert de effectiviteit van de pil via CYP3A4-inductie.",
        ),
        ContraIndication(
            medication_or_condition="Ciclosporine",
            severity="high",
            description="Sterk verlaagde ciclosporinespiegel; transplantaatafstoting mogelijk.",
        ),
    ],
    # Magnesium
    "magnesium": [
        ContraIndication(
            medication_or_condition="Tetracycline antibiotica",
            severity="medium",
            description="Magnesium vermindert de absorptie van tetracyclines.",
        ),
        ContraIndication(
            medication_or_condition="Bisfosfonaten",
            severity="medium",
            description="Magnesium kan de opname van bisfosfonaten verminderen.",
        ),
    ],
    # IJzer
    "ijzer": [
        ContraIndication(
            medication_or_condition="Levothyroxine",
            severity="medium",
            description="IJzer vermindert de absorptie van schildklierhormoon.",
        ),
        ContraIndication(
            medication_or_condition="Fluoroquinolonen",
            severity="medium",
            description="IJzer chelateert fluoroquinolonen en verlaagt hun effectiviteit.",
        ),
    ],
    # Vitamine D
    "vitamine d": [
        ContraIndication(
            medication_or_condition="Thiazidediuretica",
            severity="low",
            description="Verhoogd risico op hypercalciëmie bij hoge vitamine D-doses.",
        ),
    ],
    # Omega-3
    "omega-3": [
        ContraIndication(
            medication_or_condition="Warfarine",
            severity="low",
            description="Hoge doses omega-3 kunnen de bloedingstijd licht verlengen.",
        ),
        ContraIndication(
            medication_or_condition="Aspirine",
            severity="low",
            description="Additief bloedverdunnend effect bij hoge doses.",
        ),
    ],
}


# ---------------------------------------------------------------------------
# 1. AI Scanner Service
# ---------------------------------------------------------------------------

_SCAN_SYSTEM_PROMPT = """
Je bent een farmaceutisch expert-AI die supplement-etiketten analyseert.
Gegeven ruwe tekst van een etiket, extraheer je de informatie en retourneer je
UITSLUITEND een geldig JSON-object dat voldoet aan het volgende schema:

{
  "product_info": {
    "name": "<string>",
    "brand": "<string | null>",
    "dosage": "<string>",
    "type": "<string | null>"
  },
  "ai_logic": {
    "optimal_timing": "<string | null>",
    "primary_benefit": "<string | null>",
    "warning": "<string | null>"
  },
  "ingredients": [
    {"name": "<string>", "amount": "<string | null>"}
  ],
  "contra_indications": [
    {
      "medication_or_condition": "<string>",
      "severity": "low|medium|high",
      "description": "<string | null>"
    }
  ]
}

Regels:
- Retourneer ALLEEN het JSON-object, geen extra tekst of markdown-blokken.
- Vul ontbrekende velden in met null.
- Gebruik Nederlandse taal voor beschrijvingen.
- Voeg bekende contra-indicaties toe op basis van de ingrediënten.
""".strip()


def scan_label(raw_text: str) -> SupplementCreate:
    """
    Verwerkt ruwe etikettekst via Claude en retourneert een SupplementCreate-object.

    Parameters
    ----------
    raw_text : str
        De ruwe tekst die van een supplement-etiket is gescand.

    Returns
    -------
    SupplementCreate
        Gestructureerd supplement-object klaar voor opslag.

    Raises
    ------
    ValueError
        Als de AI-respons geen geldig JSON-object bevat.
    """
    logger.info("AI Scanner: verwerken van %d tekens ruwe etikettekst", len(raw_text))

    message = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SCAN_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Analyseer dit etiket en retourneer uitsluitend JSON:\n\n{raw_text}",
            }
        ],
    )

    raw_json = message.content[0].text
    logger.debug("AI Scanner raw response: %s", raw_json)

    # Verwijder eventuele markdown code-blokken die Claude soms toevoegt
    raw_json = raw_json.strip()
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]
        raw_json = raw_json.strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI retourneerde geen geldig JSON: {exc}\nRuwe respons: {raw_json}"
        ) from exc

    return SupplementCreate(**data)


# ---------------------------------------------------------------------------
# 2. Safety Engine
# ---------------------------------------------------------------------------

def check_safety(
    supplement: Supplement,
    user_medications: List[str],
) -> SafetyCheckResult:
    """
    Controleert of een supplement conflicteert met de medicijnen van de gebruiker.

    De engine doorzoekt:
    1. De contra_indications die al in het supplement-object zijn opgeslagen.
    2. De ingebouwde KNOWN_INTERACTIONS-database op basis van ingrediëntnamen
       en de supplementnaam.

    Parameters
    ----------
    supplement : Supplement
        Het supplement-object uit de database.
    user_medications : List[str]
        Lijst van medicijnnamen die de gebruiker gebruikt (hoofdletterongevoelig).

    Returns
    -------
    SafetyCheckResult
        Bevat alle gevonden conflicten en een veiligheidsadvies.

    TODO (Fase 2):
        Voeg allergie-check toe naast medicijn-check (R-09).
    """
    logger.info(
        "Safety Engine: controle '%s' tegen %d medicijnen",
        supplement.product_info.name,
        len(user_medications),
    )

    meds_lower = {m.lower() for m in user_medications}
    conflicts: List[ContraIndication] = []

    # --- Stap 1: check opgeslagen contra-indicaties in het supplement zelf ---
    for ci in supplement.contra_indications:
        if ci.medication_or_condition.lower() in meds_lower:
            conflicts.append(ci)

    # --- Stap 2: check KNOWN_INTERACTIONS op basis van naam + ingrediënten ---
    search_terms = {supplement.product_info.name.lower()}
    for ing in supplement.ingredients:
        search_terms.add(ing.name.lower())

    for term in search_terms:
        known = KNOWN_INTERACTIONS.get(term, [])
        for ci in known:
            if ci.medication_or_condition.lower() in meds_lower:
                # Voorkomen van duplicaten
                already = any(
                    c.medication_or_condition.lower()
                    == ci.medication_or_condition.lower()
                    for c in conflicts
                )
                if not already:
                    conflicts.append(ci)

    # --- Resultaat samenstellen ---
    safe = len(conflicts) == 0

    if safe:
        message = (
            f"✅ Geen bekende interacties gevonden tussen "
            f"'{supplement.product_info.name}' en uw medicijnen."
        )
    else:
        high = [c for c in conflicts if c.severity == "high"]
        if high:
            message = (
                f"🚨 ERNSTIGE WAARSCHUWING: '{supplement.product_info.name}' heeft "
                f"{len(high)} ernstige interactie(s) met uw medicijnen. "
                f"Raadpleeg direct uw arts of apotheker."
            )
        else:
            message = (
                f"⚠️ Let op: '{supplement.product_info.name}' heeft "
                f"{len(conflicts)} mogelijke interactie(s) met uw medicijnen. "
                f"Overleg met uw zorgverlener."
            )

    return SafetyCheckResult(
        supplement_id=supplement.id,
        supplement_name=supplement.product_info.name,
        medications_checked=user_medications,
        conflicts=conflicts,
        safe=safe,
        message=message,
    )


# ---------------------------------------------------------------------------
# 3. AI Advice Service
# ---------------------------------------------------------------------------

_ADVICE_SYSTEM_PROMPT = """
Je bent een deskundige supplementen-adviseur voor de YouCaps app.
Je geeft wetenschappelijk onderbouwd, praktisch advies over supplementen.
Antwoord altijd in het Nederlands. Wees bondig maar volledig (max 300 woorden).
Vermeld altijd dat de gebruiker een arts of apotheker moet raadplegen voor
persoonlijk medisch advies. Dit is GEEN medisch advies.
""".strip()


def get_ai_advice(supplement: Supplement, user_question: str | None = None) -> str:
    """
    Genereert AI-advies over een specifiek supplement via Claude.

    Parameters
    ----------
    supplement : Supplement
        Het supplement-object uit de database.
    user_question : str | None
        Optionele specifieke vraag van de gebruiker.

    Returns
    -------
    str
        Het AI-advies als platte tekst.
    """
    logger.info("AI Advice: advies genereren voor '%s'", supplement.product_info.name)

    supplement_summary = (
        f"Supplement: {supplement.product_info.name}\n"
        f"Merk: {supplement.product_info.brand or 'onbekend'}\n"
        f"Dosering: {supplement.product_info.dosage}\n"
        f"Vorm: {supplement.product_info.type or 'onbekend'}\n"
    )

    if supplement.ingredients:
        ing_list = ", ".join(
            f"{i.name} ({i.amount})" if i.amount else i.name
            for i in supplement.ingredients
        )
        supplement_summary += f"Ingrediënten: {ing_list}\n"

    if supplement.ai_logic:
        al = supplement.ai_logic
        if al.primary_benefit:
            supplement_summary += f"Primair voordeel: {al.primary_benefit}\n"
        if al.optimal_timing:
            supplement_summary += f"Optimale timing: {al.optimal_timing}\n"
        if al.warning:
            supplement_summary += f"Waarschuwing: {al.warning}\n"

    if user_question:
        user_content = (
            f"Hier is informatie over het supplement:\n{supplement_summary}\n\n"
            f"Vraag van de gebruiker: {user_question}"
        )
    else:
        user_content = (
            f"Geef een uitgebreid advies over dit supplement:\n{supplement_summary}"
        )

    message = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=_ADVICE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    return message.content[0].text.strip()
