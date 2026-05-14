"""
Mollie payment integration: checkout creation, webhook handling, status checks

Endpoints:
  POST /api/payment/create-checkout — create Mollie payment
  GET /api/payment/status/{payment_id} — check payment status
  POST /webhook/mollie — handle Mollie webhook
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.auth import get_current_user
from src.core.config import settings
from src.db.database import get_db
from src.db.models import Payment, Subscription, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])
webhook_router = APIRouter(tags=["webhook"])


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateCheckoutRequest(BaseModel):
    """Request to create Mollie payment checkout."""
    plan_id: str  # e.g., "premium", "pro"
    amount_cents: int  # Amount in cents (e.g., 2999 = €29.99)


class CheckoutResponse(BaseModel):
    """Response with Mollie checkout URL."""
    payment_id: str
    mollie_payment_id: str
    checkout_url: str


class PaymentStatusResponse(BaseModel):
    """Payment status response."""
    id: str
    mollie_payment_id: str
    status: str
    amount: int
    currency: str
    paid_at: str | None


class MollieWebhookRequest(BaseModel):
    """Mollie webhook payload."""
    id: str  # Mollie payment ID


# ============================================================================
# Mollie API Helper
# ============================================================================


async def _create_mollie_payment(
    amount_cents: int,
    description: str,
    webhook_url: str,
    metadata: dict,
) -> dict:
    """
    Create payment on Mollie.
    
    Returns:
        Mollie payment response with 'id' and 'links.checkout.href'
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.mollie.com/v2/payments",
            headers={"Authorization": f"Bearer {settings.mollie_api_key}"},
            json={
                "amount": {
                    "value": f"{amount_cents / 100:.2f}",
                    "currency": "EUR",
                },
                "description": description,
                "redirectUrl": metadata.get("return_url"),
                "webhookUrl": webhook_url,
                "metadata": metadata,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _get_mollie_payment_status(mollie_payment_id: str) -> dict:
    """Get payment status from Mollie."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.mollie.com/v2/payments/{mollie_payment_id}",
            headers={"Authorization": f"Bearer {settings.mollie_api_key}"},
        )
        resp.raise_for_status()
        return resp.json()


def _verify_mollie_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify Mollie webhook signature.
    
    Mollie includes an X-Mollie-Signature header.
    We re-hash the body with our webhook secret and compare.
    """
    if not settings.mollie_webhook_secret:
        logger.warning("Mollie webhook secret not configured, skipping signature verification")
        return True
    
    expected_sig = hmac.new(
        settings.mollie_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_sig)


# ============================================================================
# Payment Endpoints
# ============================================================================


@router.post("/create-checkout", response_model=CheckoutResponse)
async def create_checkout(
    req: CreateCheckoutRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Create Mollie payment checkout.
    
    Flow:
      1. Frontend calls this endpoint with plan_id and amount
      2. We create a Payment record (status='open')
      3. We create Mollie payment
      4. We return checkout_url to frontend
      5. User follows checkout_url to complete payment
      6. Mollie calls our webhook when payment succeeds
    """
    try:
        # Build webhook URL
        webhook_url = f"{settings.frontend_url.rstrip('/')}/webhook/mollie"
        # In production, this should be the actual backend webhook URL
        # webhook_url = f"https://api.sportset.app/webhook/mollie"
        
        metadata = {
            "user_id": user.id,
            "plan_id": req.plan_id,
            "return_url": f"{settings.frontend_url}/checkout?status=success",
        }
        
        # Create Mollie payment
        mollie_response = await _create_mollie_payment(
            amount_cents=req.amount_cents,
            description=f"Sportset {req.plan_id} subscription",
            webhook_url=webhook_url,
            metadata=metadata,
        )
        
        mollie_payment_id = mollie_response["id"]
        checkout_url = mollie_response["_links"]["checkout"]["href"]
        
        # Store payment record
        payment = Payment(
            user_id=user.id,
            mollie_payment_id=mollie_payment_id,
            amount=req.amount_cents,
            currency="EUR",
            status="open",
            mollie_checkout_url=checkout_url,
            plan_id=req.plan_id,
            metadata=json.dumps(metadata),
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        
        logger.info(f"Payment created: {payment.id} (user={user.id}, mollie={mollie_payment_id})")
        
        return CheckoutResponse(
            payment_id=payment.id,
            mollie_payment_id=mollie_payment_id,
            checkout_url=checkout_url,
        )
    
    except Exception as e:
        logger.error(f"Mollie payment creation failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to create payment")


@router.get("/status/{mollie_payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    mollie_payment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get payment status from our database."""
    payment = db.query(Payment).filter(
        Payment.mollie_payment_id == mollie_payment_id,
        Payment.user_id == user.id,
    ).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    return PaymentStatusResponse(
        id=payment.id,
        mollie_payment_id=payment.mollie_payment_id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        paid_at=payment.paid_at.isoformat() if payment.paid_at else None,
    )


# ============================================================================
# Webhook Endpoint (for Mollie)
# ============================================================================


@webhook_router.post("/webhook/mollie", status_code=status.HTTP_204_NO_CONTENT)
async def mollie_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Mollie webhook: payment status update.
    
    Mollie sends:
      - X-Mollie-Signature header with HMAC-SHA256
      - POST body with 'id' (Mollie payment ID)
    """
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify signature if webhook secret is configured
    signature = request.headers.get("X-Mollie-Signature", "")
    if not _verify_mollie_webhook_signature(body, signature):
        logger.warning("Mollie webhook signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")
    
    # Parse payload
    try:
        payload = json.loads(body)
        mollie_payment_id = payload["id"]
    except (json.JSONDecodeError, KeyError):
        logger.error(f"Invalid Mollie webhook payload: {body}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    
    # Get payment status from Mollie
    try:
        mollie_response = await _get_mollie_payment_status(mollie_payment_id)
    except Exception as e:
        logger.error(f"Failed to get Mollie payment status: {e}")
        raise HTTPException(status_code=502, detail="Failed to verify payment")
    
    # Update payment record in our database
    payment = db.query(Payment).filter(
        Payment.mollie_payment_id == mollie_payment_id
    ).first()
    
    if not payment:
        logger.warning(f"Received webhook for unknown Mollie payment: {mollie_payment_id}")
        return
    
    mollie_status = mollie_response["status"]
    payment.status = mollie_status
    
    if mollie_status == "paid":
        payment.paid_at = datetime.now(timezone.utc)
        
        # Auto-create/update subscription on successful payment
        subscription = db.query(Subscription).filter(
            Subscription.user_id == payment.user_id
        ).first()
        
        if subscription:
            subscription.status = "active"
            subscription.renewal_date = datetime.now(timezone.utc) + timedelta(days=30)
        else:
            subscription = Subscription(
                user_id=payment.user_id,
                plan_id=payment.plan_id,
                status="active",
                renewal_date=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.add(subscription)
        
        # Update user subscription status
        user = db.query(User).filter(User.id == payment.user_id).first()
        if user:
            user.subscription_status = "active"
        
        logger.info(f"Payment confirmed: {payment.id} (user={payment.user_id})")
    
    elif mollie_status == "expired" or mollie_status == "failed" or mollie_status == "cancelled":
        logger.warning(f"Payment {mollie_status}: {payment.id}")
    
    db.commit()
    logger.info(f"Mollie webhook processed: {mollie_payment_id} -> {mollie_status}")
