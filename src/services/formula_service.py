from src.schemas.onboarding import FormulaItem

# Gespiegeld aan frontend/src/api/mockData.js — niet aanpassen zonder frontend te syncon
_BASE_FORMULAS: dict[str, list[dict]] = {
    "energy": [
        {"name": "Vitamine B12",     "desc": "Energiehuishouding en zenuwstelsel",    "dose": "1000mcg"},
        {"name": "Magnesium Malaat", "desc": "Spierfunctie en cellulaire energie",     "dose": "400mg"},
        {"name": "CoQ10",            "desc": "Mitochondriale ondersteuning",           "dose": "100mg"},
    ],
    "sleep": [
        {"name": "Melatonine",          "desc": "Slaap-waakritme",                    "dose": "0.5mg"},
        {"name": "Magnesium Glycinaat", "desc": "Ontspanning spieren en geest",       "dose": "300mg"},
        {"name": "Ashwagandha",         "desc": "Vermindert avondstress",             "dose": "600mg"},
    ],
    "muscle": [
        {"name": "Creatine Monohydraat", "desc": "Kracht en hersteltijd",             "dose": "5g"},
        {"name": "Vitamine D3 + K2",     "desc": "Bot- en spierfunctie",              "dose": "5000IU / 100mcg"},
        {"name": "Zink",                 "desc": "Eiwitsynthese en herstel",          "dose": "15mg"},
    ],
    "immune": [
        {"name": "Vitamine C",         "desc": "Immuunondersteuning",                 "dose": "1000mg"},
        {"name": "Zink Bisglycinaat",  "desc": "Immuunreactie",                       "dose": "15mg"},
        {"name": "Vitamine D3",        "desc": "Immuun- en botfunctie",               "dose": "4000IU"},
    ],
    "stress": [
        {"name": "Ashwagandha KSM-66", "desc": "Cortisolbalans",                      "dose": "600mg"},
        {"name": "L-Theanine",         "desc": "Kalme focus zonder sufheid",          "dose": "200mg"},
        {"name": "Rhodiola Rosea",     "desc": "Mentale weerbaarheid",                "dose": "300mg"},
    ],
}

# Add-ons per dieet — toegevoegd als ze nog niet in de basisformule zitten
# Positioneringscopy: beschrijvende termen, geen gezondheidsclaims (EU 1924/2006)
_DIET_ADDONS: dict[str, list[dict]] = {
    "omnivoor": [],
    "vegetarisch": [
        {"name": "IJzer Bisglycinaat", "desc": "Goed opneembare ijzervariant voor plantaardige voeding", "dose": "18mg"},
    ],
    "veganistisch": [
        {"name": "IJzer Bisglycinaat", "desc": "Goed opneembare ijzervariant voor plantaardige voeding", "dose": "18mg"},
        {"name": "Omega-3 DHA",        "desc": "Plantaardige DHA uit algenextract",                     "dose": "250mg"},
    ],
    "glutenvrij": [
        {"name": "Vitamine B-complex", "desc": "Aanvulling bij graanvrije voeding",                     "dose": "1 capsule"},
    ],
}


def build_formula(goal: str, diet: str) -> list[FormulaItem]:
    base = list(_BASE_FORMULAS.get(goal, []))
    addons = _DIET_ADDONS.get(diet, [])

    existing = {item["name"].lower() for item in base}
    for addon in addons:
        if addon["name"].lower() not in existing:
            base.append(addon)

    return [FormulaItem(**item) for item in base]
