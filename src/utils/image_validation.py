"""
backend/utils/image_validation.py
---------------------------------
Veilige image-validatie en preprocessing voor de YouCaps Vision Scanner.

Verantwoordelijkheden
---------------------
1. MIME-detectie via *magic bytes* — de Content-Type header wordt nooit vertrouwd.
2. Decompression-bom-bescherming via Pillow's `MAX_IMAGE_PIXELS`.
3. Frame-count-controle (animated GIF/WebP wordt geweigerd).
4. Dimensie-bounds (min/max).
5. EXIF-orientatie wordt fysiek toegepast en daarna gestript (privacy: GPS-data
   gaat nooit naar de AI of disk).
6. Resize tot een door Anthropic geadviseerde max. zijde.
7. Re-encoding naar JPEG q85 (klein, schoon, zonder metadata).
8. SHA-256 hash van de geprocesste bytes voor audit-trail (de bytes zelf
   worden NIET op disk opgeslagen).

Alle CPU-zware bewerkingen kunnen via ``preprocess_image`` worden aangeroepen;
in een async context kun je dat in een thread-executor wrappen.

Veiligheidsprincipes
--------------------
* "Fail closed" — onbekende formaten of corrupte data → exception, geen fallback.
* Geen tijdelijke bestanden, alles in-memory.
* Strikte max-grootte controle voordat Pillow het bestand opent.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pillow safety — voorkomt decompression-bombs (zip-bomb-equivalent voor PNG).
# ---------------------------------------------------------------------------
# 50 megapixels is ruim genoeg voor zelfs zeer hoge-resolutie foto's
# (bijv. iPhone 15 Pro: 48 MP) maar ver onder pathologische "PNG bomb" bestanden.
Image.MAX_IMAGE_PIXELS = 50_000_000


# ---------------------------------------------------------------------------
# Foutklassen — typed zodat de routelaag specifieke HTTP-codes kan kiezen.
# ---------------------------------------------------------------------------

class ImageValidationError(Exception):
    """Basisklasse voor alle image-validatiefouten."""

    error_code: str = "invalid_image"
    http_status: int = 400


class UploadTooLargeError(ImageValidationError):
    error_code = "upload_too_large"
    http_status = 413


class UnsupportedImageFormatError(ImageValidationError):
    error_code = "unsupported_image_format"
    http_status = 415


class CorruptImageError(ImageValidationError):
    error_code = "invalid_image"
    http_status = 400


class ImageDimensionError(ImageValidationError):
    error_code = "invalid_image"
    http_status = 400


# ---------------------------------------------------------------------------
# MIME-detectie via magic bytes
# ---------------------------------------------------------------------------
# We accepteren bewust géén HEIC/HEIF (Pillow ondersteunt het niet zonder
# `pillow-heif` plugin) en géén TIFF (te vaak misbruikt voor multi-page exploits).
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    # WebP: 'RIFF' .... 'WEBP'
    # We checken eerst RIFF en pas in `_detect_mime` of bytes 8-11 == b"WEBP".
    (b"RIFF", "image/webp-candidate"),
)

_ALLOWED_MIME: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})


def _detect_mime(raw: bytes) -> str:
    """
    Bepaalt het MIME-type op basis van de eerste bytes van het bestand.

    Raises
    ------
    UnsupportedImageFormatError
        Als het bestand geen herkend image-formaat is, of een geweigerd
        formaat (HEIC, GIF, BMP, TIFF, SVG, PDF, ...).
    """
    if len(raw) < 12:
        raise UnsupportedImageFormatError("Bestand is te klein om een afbeelding te zijn.")

    for signature, mime in _MAGIC_SIGNATURES:
        if raw.startswith(signature):
            if mime == "image/webp-candidate":
                # Volledige WebP-check: 'RIFF' [4 bytes size] 'WEBP'
                if raw[8:12] == b"WEBP":
                    return "image/webp"
                raise UnsupportedImageFormatError(
                    "RIFF-container herkend maar geen geldige WebP-payload."
                )
            return mime

    # Expliciete reject voor formaten die we wel kunnen detecteren maar weigeren
    if raw.startswith((b"GIF87a", b"GIF89a")):
        raise UnsupportedImageFormatError("GIF wordt niet ondersteund — gebruik JPEG, PNG of WebP.")
    if raw.startswith(b"BM"):
        raise UnsupportedImageFormatError("BMP wordt niet ondersteund — gebruik JPEG, PNG of WebP.")
    if raw[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        raise UnsupportedImageFormatError(
            "HEIC/HEIF wordt niet ondersteund. Sla de foto op als JPEG of PNG."
        )

    raise UnsupportedImageFormatError(
        "Onbekend bestandsformaat. Alleen JPEG, PNG en WebP zijn toegestaan."
    )


# ---------------------------------------------------------------------------
# Resultaat-container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PreprocessedImage:
    """Resultaat van preprocess_image."""

    bytes_jpeg: bytes
    media_type: str
    width: int
    height: int
    sha256: str
    original_mime: str
    original_size_bytes: int

    @property
    def size_bytes(self) -> int:
        return len(self.bytes_jpeg)


# ---------------------------------------------------------------------------
# Hoofdfunctie
# ---------------------------------------------------------------------------

def preprocess_image(raw: bytes) -> PreprocessedImage:
    """
    Valideert en preprocest een geüploade afbeelding.

    Volgorde van checks (snel → duur):
      1. byte-grootte ≤ MAX_UPLOAD_BYTES
      2. MIME via magic bytes
      3. Pillow open + verify (corrupt?)
      4. frames-count check
      5. dimensies in [min, max] range
      6. EXIF-orientatie toepassen
      7. resize naar MAX_DIMENSION (langste zijde)
      8. convert RGB + re-encode JPEG q85 (strips metadata)
      9. SHA-256 hash van de eindbytes

    Parameters
    ----------
    raw : bytes
        Het rauwe upload-payload.

    Returns
    -------
    PreprocessedImage

    Raises
    ------
    UploadTooLargeError, UnsupportedImageFormatError, CorruptImageError, ImageDimensionError
    """
    original_size = len(raw)

    # 1. Grootte
    if original_size == 0:
        raise CorruptImageError("Leeg bestand ontvangen.")
    if original_size > settings.max_upload_bytes:
        raise UploadTooLargeError(
            f"Bestand is {original_size / 1024 / 1024:.1f} MB; max is "
            f"{settings.max_upload_mb} MB."
        )

    # 2. MIME via magic bytes
    mime = _detect_mime(raw)
    if mime not in _ALLOWED_MIME:
        raise UnsupportedImageFormatError(f"MIME-type '{mime}' is niet toegestaan.")

    # 3. Open & verify
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()  # detecteert corrupte payloads
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise CorruptImageError(f"Afbeelding is corrupt of onleesbaar: {exc}") from exc
    except Image.DecompressionBombError as exc:
        raise CorruptImageError(
            "Afbeelding overschrijdt de decompressie-veiligheidslimiet."
        ) from exc

    # 4 & 5. Heropen voor verdere bewerking — verify() invalidates the image object.
    try:
        img = Image.open(io.BytesIO(raw))
        # Frame-count check (animated GIF/WebP)
        n_frames = getattr(img, "n_frames", 1)
        if n_frames > 1:
            raise UnsupportedImageFormatError(
                "Geanimeerde afbeeldingen worden niet ondersteund. Upload een stilstaande foto."
            )

        # Dimensies vóór EXIF-rotatie ophalen — exif_transpose draait wijdte/hoogte indien nodig
        w, h = img.size
        if w < settings.image_min_dimension or h < settings.image_min_dimension:
            raise ImageDimensionError(
                f"Afbeelding te klein: {w}×{h}px. Minimaal "
                f"{settings.image_min_dimension}×{settings.image_min_dimension}px vereist."
            )
        if w > 12000 or h > 12000:
            raise ImageDimensionError(
                f"Afbeelding te groot: {w}×{h}px. Maximaal 12000px per zijde."
            )

        # 6. EXIF-orientatie toepassen (fysieke pixel-rotatie, geen tag)
        img = ImageOps.exif_transpose(img)

        # 7. Resize naar MAX_DIMENSION zonder vervorming
        max_dim = settings.image_max_dimension
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # 8. Convert + re-encode JPEG (strip metadata)
        if img.mode != "RGB":
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(
            out,
            format="JPEG",
            quality=85,
            optimize=True,
            progressive=False,
            exif=b"",  # strip EXIF
            icc_profile=None,
        )
        out_bytes = out.getvalue()
        final_w, final_h = img.size
    except ImageValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise CorruptImageError("Decompressie-bom gedetecteerd.") from exc
    except Exception as exc:  # pragma: no cover — fail-closed
        logger.exception("Onverwachte preprocessing-fout: %s", exc)
        raise CorruptImageError(f"Kon afbeelding niet verwerken: {exc}") from exc

    sha = hashlib.sha256(out_bytes).hexdigest()

    logger.info(
        "Image preprocessing OK | mime=%s in_bytes=%d out_bytes=%d size=%dx%d sha=%s",
        mime,
        original_size,
        len(out_bytes),
        final_w,
        final_h,
        sha[:12],
    )

    return PreprocessedImage(
        bytes_jpeg=out_bytes,
        media_type="image/jpeg",
        width=final_w,
        height=final_h,
        sha256=sha,
        original_mime=mime,
        original_size_bytes=original_size,
    )


# ---------------------------------------------------------------------------
# Hulp: streamed read met harde cap
# ---------------------------------------------------------------------------

async def read_upload_capped(stream, max_bytes: int) -> bytes:
    """
    Leest een upload (FastAPI ``UploadFile.read()`` geeft alles tegelijk;
    voor zeer grote bestanden gebruiken we ``stream`` in chunks). Als de
    cap wordt overschreden gooien we direct een ``UploadTooLargeError``,
    voordat we het hele bestand in geheugen hoeven te bufferen.

    Parameters
    ----------
    stream : object
        Een object met een async ``read(size)``-methode (zoals
        ``starlette.datastructures.UploadFile``).
    max_bytes : int
        Strikte bovengrens (inclusief).

    Returns
    -------
    bytes
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(
                f"Upload overschrijdt de max van {max_bytes / 1024 / 1024:.0f} MB."
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Test-helper: één-line wrapper voor synchroon gebruik in scripts.
# ---------------------------------------------------------------------------

def quick_preprocess(path: str) -> Tuple[PreprocessedImage, bytes]:
    """
    Lees `path` van disk en voer preprocess_image uit. Alleen voor lokale tests.
    Niet gebruikt in productie-paden.
    """
    with open(path, "rb") as f:
        raw = f.read()
    return preprocess_image(raw), raw
