"""
backend/api/upload.py
---------------------
HTTP-route voor de Vision Scanner.

POST /api/scan/upload    multipart/form-data, field name: ``image``

Beveiligings-defenses (in volgorde van uitvoering)
--------------------------------------------------
1. SlowAPI rate-limit  (per IP, configureerbaar)
2. Content-Length pre-check  (snelle 413 voordat body geparsed wordt)
3. Streamed read met harde cap  (DOS-bescherming)
4. Magic-byte MIME-validatie + dimensies + EXIF-strip
5. Async preprocessing in thread-executor (CPU-bound, geen event-loop block)
6. Anthropic Vision call met timeout + retry
7. Pydantic-validatie van AI-output
8. Matching tegen verifieerbare knowledge base
9. Persist naar SQLite + AuditLog via BackgroundTasks (geen latency-impact)

Foutformaat
-----------
Alle fouten geven een ``ScanErrorResponse`` JSON met `error_code` en `message`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.database import SessionLocal, get_db
from src.models.orm_models import AuditLogORM, ScanORM
from src.models.scan_schemas import (
    ScanErrorResponse,
    ScanMeta,
    ScanResponse,
)
from src.services.matching_service import analyze as analyze_matches
from src.services.vision_service import (
    VisionInvalidResponseError,
    VisionServiceError,
    VisionTimeoutError,
    VisionUnavailableError,
    extract_label,
)
from src.utils.image_validation import (
    ImageValidationError,
    UploadTooLargeError,
    preprocess_image,
    read_upload_capped,
)

logger = logging.getLogger(__name__)

# Hoofdrouter: registreert zowel /scan/upload (legacy/intern) als /v1/scan
# (nieuwe, gepubliceerde route die zichtbaar is in /docs en gebruikt wordt
# door de mobiele frontend).
router = APIRouter(prefix="/scan", tags=["scan"])

# Aliasrouter voor /api/v1/scan — exact dezelfde handler, maar dan onder
# een versie-gestuurde URL. Wordt gemount in main.py met prefix "/api/v1".
v1_router = APIRouter(prefix="/v1", tags=["scan-v1"])

# SlowAPI limiter — gedeeld via app.state in main.py.
# We definiëren hier een lokale `limiter` referentie omdat slowapi-decorators
# de Limiter direct nodig hebben. Hij wordt geconnect aan dezelfde state.
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(error_code: str, message: str, http_status: int, detail: str | None = None) -> JSONResponse:
    body = ScanErrorResponse(error_code=error_code, message=message, detail=detail)
    return JSONResponse(status_code=http_status, content=body.model_dump())


def _persist_scan_and_audit(
    *,
    scan_id: str,
    extraction_dict: dict[str, Any],
    product_name: str | None,
    brand: str | None,
    overall_confidence: float,
    model_name: str,
    ai_attempts: int,
    latency_ms: int,
    image_hash: str,
    image_bytes: int,
    image_width: int,
    image_height: int,
    user_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
    status_code: int,
) -> None:
    """
    Schrijft één ScanORM-record en één AuditLogORM-record naar de DB.
    Wordt uitgevoerd in een ``BackgroundTask`` zodat de HTTP-response al weg is.
    """
    db: Session = SessionLocal()
    try:
        scan = ScanORM(
            id=scan_id,
            user_id=user_id,
            product_name=product_name,
            brand=brand,
            overall_confidence=overall_confidence,
            raw_extraction=extraction_dict,
            model_name=model_name,
            ai_attempts=ai_attempts,
            latency_ms=latency_ms,
            image_hash=image_hash,
            image_bytes=image_bytes,
            image_width=image_width,
            image_height=image_height,
        )
        db.add(scan)

        audit = AuditLogORM(
            user_id=user_id,
            action="scan_label",
            resource_type="scan",
            resource_id=scan_id,
            payload_hash=image_hash,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
            status_code=status_code,
        )
        db.add(audit)
        db.commit()
    except Exception:
        logger.exception("Persist van scan %s mislukt", scan_id)
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    summary="Upload supplement-foto en ontvang AI-analyse",
    response_model=ScanResponse,
    responses={
        400: {"model": ScanErrorResponse},
        413: {"model": ScanErrorResponse},
        415: {"model": ScanErrorResponse},
        429: {"model": ScanErrorResponse},
        502: {"model": ScanErrorResponse},
        503: {"model": ScanErrorResponse},
        504: {"model": ScanErrorResponse},
    },
)
@limiter.limit(settings.rate_limit_scan)
async def upload_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(..., description="Foto van het supplement-etiket (JPEG/PNG/WebP)"),
    db: Session = Depends(get_db),
) -> Any:
    return await _process_scan(request, background_tasks, image, db)


# ---------------------------------------------------------------------------
# Versie-gestuurde alias: POST /api/v1/scan
# ---------------------------------------------------------------------------
# Dit is de route die de mobiele frontend gebruikt. Ze deelt de complete
# pipeline met /api/scan/upload (zelfde handler, zelfde rate-limit), maar
# heeft een stabieler, semantisch URL-pad dat in de OpenAPI-docs verschijnt.
@v1_router.post(
    "/scan",
    summary="Scan supplement-foto (v1) — vision + matching pipeline",
    response_model=ScanResponse,
    responses={
        400: {"model": ScanErrorResponse},
        413: {"model": ScanErrorResponse},
        415: {"model": ScanErrorResponse},
        429: {"model": ScanErrorResponse},
        502: {"model": ScanErrorResponse},
        503: {"model": ScanErrorResponse},
        504: {"model": ScanErrorResponse},
    },
)
@limiter.limit(settings.rate_limit_scan)
async def scan_v1(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(..., description="Foto van het supplement-etiket (JPEG/PNG/WebP)"),
    db: Session = Depends(get_db),
) -> Any:
    """
    Identiek aan ``POST /api/scan/upload`` maar onder een versie-gestuurde URL
    (``/api/v1/scan``) voor stabiliteit van mobiele clients.
    """
    return await _process_scan(request, background_tasks, image, db)


async def _process_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile,
    db: Session,
) -> Any:
    """
    Hoofd-endpoint voor het scannen van een supplement-etiket.
    """
    # 1. Snelle Content-Length pre-check (gepubliceerd door browser).
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > settings.max_upload_bytes + 4096:
        return _err(
            "upload_too_large",
            f"Bestand is te groot. Max {settings.max_upload_mb} MB.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    # 2. Stream-bounded read.
    try:
        raw_bytes = await read_upload_capped(image, settings.max_upload_bytes)
    except UploadTooLargeError as exc:
        return _err("upload_too_large", str(exc), status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    except Exception as exc:
        logger.exception("Onbekende fout bij upload-read: %s", exc)
        return _err("internal_error", "Kon upload niet lezen.", status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        try:
            await image.close()
        except Exception:
            pass

    # 3. Image-validatie + preprocessing in thread-executor (CPU-bound).
    loop = asyncio.get_running_loop()
    try:
        prepped = await loop.run_in_executor(None, preprocess_image, raw_bytes)
    except ImageValidationError as exc:
        return _err(exc.error_code, str(exc), exc.http_status)
    except Exception as exc:
        logger.exception("Onverwachte preprocessing-fout: %s", exc)
        return _err(
            "invalid_image",
            "Kon de afbeelding niet verwerken.",
            status.HTTP_400_BAD_REQUEST,
        )

    # 4. Vision-call.
    try:
        vision = await extract_label(prepped)
    except (VisionUnavailableError, VisionTimeoutError, VisionInvalidResponseError) as exc:
        return _err(exc.error_code, str(exc), exc.http_status)
    except VisionServiceError as exc:
        return _err(exc.error_code, str(exc), exc.http_status)
    except Exception as exc:
        logger.exception("Onverwachte vision-fout: %s", exc)
        return _err(
            "internal_error",
            "Onverwachte fout in AI-pijp.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 5. Matching tegen knowledge base + supplement-DB.
    try:
        match_output = analyze_matches(vision.extraction, db)
    except Exception as exc:
        logger.exception("Matching-fout: %s", exc)
        # Fallback: lever de extractie alsnog terug zonder matching/risk-info
        match_output = None  # type: ignore[assignment]

    # 6. Bouw response.
    scan_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    extraction_dict = vision.extraction.model_dump(mode="json")

    response = ScanResponse(
        success=True,
        extraction=vision.extraction,
        matches=match_output.matches if match_output else [],
        risks=match_output.risks if match_output else [],
        overall_confidence=match_output.overall_confidence
        if match_output
        else vision.extraction.confidence,
        meta=ScanMeta(
            scan_id=scan_id,
            model=vision.model,
            latency_ms=vision.latency_ms,
            image_hash=prepped.sha256,
            image_bytes=prepped.size_bytes,
            created_at=now,
            ai_attempts=vision.attempts,
        ),
    )

    # 7. Persist via BackgroundTask zodat de gebruiker meteen z'n response heeft.
    background_tasks.add_task(
        _persist_scan_and_audit,
        scan_id=scan_id,
        extraction_dict=extraction_dict,
        product_name=vision.extraction.product_name,
        brand=vision.extraction.brand,
        overall_confidence=response.overall_confidence,
        model_name=vision.model,
        ai_attempts=vision.attempts,
        latency_ms=vision.latency_ms,
        image_hash=prepped.sha256,
        image_bytes=prepped.size_bytes,
        image_width=prepped.width,
        image_height=prepped.height,
        user_id=None,  # Auth komt in een latere fase
        ip_address=get_remote_address(request),
        user_agent=request.headers.get("user-agent"),
        status_code=200,
    )

    return response


# ---------------------------------------------------------------------------
# Health-endpoint specifiek voor scanner-pijp (debug)
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    summary="Status van de scanner-pijp",
    include_in_schema=True,
)
async def scanner_health() -> dict:
    """
    Snelle status: KB geladen? Anthropic-key aanwezig?
    Schiet GEEN AI-aanroep af — handig voor health-checks zonder kosten.
    """
    from src.services.matching_service import KB_INDEX

    return {
        "kb_loaded": KB_INDEX.is_loaded,
        "kb_entries": KB_INDEX.size,
        "anthropic_key_present": bool(settings.anthropic_api_key),
        "vision_model": settings.vision_model,
        "max_upload_mb": settings.max_upload_mb,
        "rate_limit_scan": settings.rate_limit_scan,
    }
