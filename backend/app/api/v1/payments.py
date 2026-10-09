from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import stripe

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.payment import Payment
from app.models.review import Review
from app.api.v1.payment_schemas import (
    CheckoutRequest,
    CheckoutResponse,
    PaymentResponse,
)

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/payments", tags=["Payments"])


# Pricing (in cents)
PRICES = {
    "sop_review": 4900,  # $49.00 for expert SOP review
    "premium_month": 1900,  # $19/month premium subscription  
    "premium_year": 19900,  # $199/year premium subscription
}


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create Stripe checkout session for payment.
    """
    # Validate product type
    if request.product_type not in PRICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid product type. Must be one of: {list(PRICES.keys())}"
        )
    
    amount = PRICES[request.product_type]
    
    # For SOP review, verify document exists
    if request.product_type == "sop_review":
        if not request.product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="product_id required for SOP review"
            )
        
        from app.models.user_document import UserDocument
        result = await db.execute(
            select(UserDocument)
            .where(UserDocument.id == request.product_id)
            .where(UserDocument.user_id == current_user.id)
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
    
    # Create Stripe checkout session
    try:
        checkout_session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount,
                        "product_data": {
                            "name": f"{request.product_type.replace('_', ' ').title()}",
                            "description": _get_product_description(request.product_type),
                        },
                    },
                    "quantity": 1,
                },
            ],
            mode="payment",
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            metadata={
                "user_id": current_user.id,
                "product_type": request.product_type,
                "product_id": request.product_id or "",
            },
        )
        
        # Create pending payment record
        payment = Payment(
            user_id=current_user.id,
            stripe_payment_intent_id=checkout_session.payment_intent or checkout_session.id,
            amount=amount,
            currency="usd",
            status="pending",
            product_type=request.product_type,
            product_id=request.product_id,
        )
        db.add(payment)
        await db.commit()
        
        return CheckoutResponse(
            checkout_url=checkout_session.url,
            session_id=checkout_session.id,
        )
    
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Stripe webhook events.
    
    This endpoint is called by Stripe to notify about payment events.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        await _handle_successful_payment(session, db)
    
    elif event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        # Update payment status if needed
        pass
    
    return {"status": "success"}


@router.get("/history", response_model=list[PaymentResponse])
async def get_payment_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's payment history."""
    
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == current_user.id)
        .order_by(desc(Payment.created_at))
    )
    payments = result.scalars().all()
    
    return payments


async def _handle_successful_payment(session: dict, db: AsyncSession):
    """Handle successful payment from webhook."""
    metadata = session.get("metadata", {})
    user_id = int(metadata.get("user_id"))
    product_type = metadata.get("product_type")
    product_id = metadata.get("product_id")
    
    # Update payment record
    result = await db.execute(
        select(Payment)
        .where(Payment.stripe_payment_intent_id == session.get("payment_intent", session.get("id")))
    )
    payment = result.scalar_one_or_none()
    
    if payment:
        payment.status = "succeeded"
        payment.completed_at = datetime.utcnow()
        payment.stripe_customer_id = session.get("customer")
    
    # Create review ticket if SOP review
    if product_type == "sop_review" and product_id:
        review = Review(
            user_id=user_id,
            document_id=int(product_id),
            status="pending",
            payment_id=payment.id if payment else None,
        )
        db.add(review)
    
    await db.commit()


def _get_product_description(product_type: str) -> str:
    """Get product description."""
    descriptions = {
        "sop_review": "Expert review of your Statement of Purpose by visa and admissions professionals",
        "premium_month": "Premium features for 1 month - unlimited queries, priority support",
        "premium_year": "Premium features for 1 year - unlimited queries, priority support, best value",
    }
    return descriptions.get(product_type, product_type)
