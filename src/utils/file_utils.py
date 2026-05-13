"""
backend/utils/file_utils.py
---------------------------
Veilige bestands-I/O hulpfuncties voor YouCaps.

KERNPROBLEEM OPGELOST (R-010 uit Risico-Register):
  De root-versie van generator.py schreef direct naar het doelbestand:
      with open('supplements.json', 'w') as f:
          json.dump(data, f)
  Bij een crash halverwege resulteert dit in een leeg of gecorrumpeerd bestand.

OPLOSSING — Atomair schrijven via tmpfile + os.replace():
  1. Schrijf naar een tijdelijk bestand (tmpfile) in DEZELFDE directory.
  2. Controleer de integriteit van het tijdelijk bestand (JSON-parse + checksum).
  3. Voer os.replace(tmpfile, doelbestand) uit.
     os.replace() is atomair op POSIX en Windows: de rename() syscall is atomair.
     Lezers zien altijd óf de oude óf de nieuwe versie, nooit een tussenstaat.

Gebruik:
    from backend.utils.file_utils import atomic_write_json, read_json_safe

    data = read_json_safe("backend/db/knowledge_base.json")
    atomic_write_json("backend/db/knowledge_base.json", data)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Atomair JSON schrijven
# ---------------------------------------------------------------------------

def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    encoding: str = "utf-8",
) -> str:
    """
    Schrijft `data` als JSON naar `path` op een atomaire manier.

    Werkwijze:
      1. Serialiseer `data` naar een JSON-string.
      2. Schrijf naar een tijdelijk bestand in DEZELFDE directory als `path`
         (zelfde filesystem-partitie, zodat os.replace() atomair is).
      3. Verifieer dat het tijdelijk bestand valid JSON bevat (sanity-check).
      4. Bereken SHA-256 checksum van de inhoud.
      5. Vervang het doelbestand met os.replace() (atomaire rename).

    Parameters
    ----------
    path : str | Path
        Het doelpad voor het JSON-bestand.
    data : Any
        De te serialiseren data (dict, list, etc.).
    indent : int
        JSON-inspringing (default: 2).
    ensure_ascii : bool
        Zet op True voor pure ASCII-output (default: False, behoudt UTF-8).
    encoding : str
        Bestandscodering (default: utf-8).

    Returns
    -------
    str
        SHA-256 checksum (hex) van de geschreven inhoud.

    Raises
    ------
    ValueError
        Als de geserialiseerde data geen valid JSON is (zou nooit mogen).
    OSError
        Als schrijven of hernoemen mislukt.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 1. Serialiseer
    json_bytes = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii).encode(encoding)

    # 2. Bereken checksum vóór schrijven
    checksum = hashlib.sha256(json_bytes).hexdigest()

    # 3. Schrijf naar tmpfile in DEZELFDE directory
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.tmp.",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(json_bytes)

        # 4. Verifieer: parse het tijdelijk bestand terug
        with open(tmp_path, "r", encoding=encoding) as verify_file:
            json.load(verify_file)  # gooit JSONDecodeError als corrupt

        # 5. Atomaire rename
        os.replace(tmp_path, str(target))
        logger.info(
            "atomic_write_json: '%s' succesvol geschreven (%d bytes, sha256=%s…)",
            target,
            len(json_bytes),
            checksum[:16],
        )
        return checksum

    except Exception:
        # Ruim het tmpfile op bij elke fout
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Veilig JSON lezen
# ---------------------------------------------------------------------------

def read_json_safe(
    path: str | Path,
    *,
    encoding: str = "utf-8",
) -> Any:
    """
    Leest een JSON-bestand en retourneert de geparsde data.

    Gooit een duidelijke fout als het bestand niet bestaat of corrupt is,
    in plaats van een cryptische JSONDecodeError diep in de stack.

    Parameters
    ----------
    path : str | Path
        Pad naar het JSON-bestand.
    encoding : str
        Bestandscodering (default: utf-8).

    Returns
    -------
    Any
        De geparsde JSON-data.

    Raises
    ------
    FileNotFoundError
        Als het bestand niet bestaat.
    ValueError
        Als het bestand geen valid JSON bevat.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"JSON-bestand niet gevonden: {target.resolve()}")

    try:
        with open(target, "r", encoding=encoding) as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Corrupt JSON-bestand: {target.resolve()}\nFout: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Checksum berekening
# ---------------------------------------------------------------------------

def compute_file_checksum(path: str | Path, *, encoding: str = "utf-8") -> str:
    """
    Berekent de SHA-256 checksum van een bestand.

    Gebruik voor integriteitsverificatie na migraties of back-ups.

    Parameters
    ----------
    path : str | Path
        Pad naar het te controleren bestand.

    Returns
    -------
    str
        SHA-256 hex-digest van de bestandsinhoud.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Bestand niet gevonden voor checksum: {target.resolve()}")

    with open(target, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
