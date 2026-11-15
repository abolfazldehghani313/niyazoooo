from datetime import datetime, timezone
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Payment, User, Wallet, WalletTransaction
from app.services import BazaarPay, IntegrationError

router = APIRouter(tags=["پیامک و پرداخت"])

def credit_wallet_for_payment(db: Session, payment: Payment):
    """Credit a wallet top-up once, only after BazaarPay reports committed payment."""
    if payment.service_name != "شارژ کیف پول" or payment.status != "paid":
        return
    existing = db.query(WalletTransaction).filter(WalletTransaction.payment_id == payment.id).first()
    if existing:
        return
    wallet = db.query(Wallet).filter(Wallet.user_id == payment.user_id).with_for_update().first()
    if wallet is None:
        wallet = Wallet(user_id=payment.user_id, balance=0)
        db.add(wallet)
        db.flush()
    wallet.balance += payment.amount
    db.add(WalletTransaction(user_id=payment.user_id, payment_id=payment.id, amount=payment.amount,
                             kind="credit", title="شارژ کیف پول"))
    db.flush()

@router.get('/wallet')
def wallet_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
    return {"user_id": user.id, "balance": wallet.balance if wallet else 0, "currency": "TOMAN"}

@router.get('/wallet/transactions')
def wallet_transactions(limit: int = Query(30, ge=1, le=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id).order_by(WalletTransaction.created_at.desc()).limit(limit).all()
    return {"items": [{"id": x.id, "payment_id": x.payment_id, "amount": x.amount, "kind": x.kind, "title": x.title, "created_at": x.created_at.isoformat()} for x in rows]}

class PaymentCreate(BaseModel):
    amount: int = Field(gt=0, le=1_000_000_000)
    service_name: str = Field(min_length=2, max_length=200)

@router.post('/payments/init')
async def create_payment(body: PaymentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.amount < settings.payment_min_amount or body.amount > settings.payment_max_amount:
        raise HTTPException(422, detail='مبلغ پرداخت خارج از محدوده مجاز است')
    if not settings.bazaarpay_destination:
        raise HTTPException(503, detail='تنظیم BAZAARPAY_DESTINATION در سرور انجام نشده است')
    try:
        result = await BazaarPay().init(body.amount, settings.bazaarpay_destination, body.service_name)
    except IntegrationError as exc:
        raise HTTPException(502, detail=str(exc))
    checkout_token = result.get('checkout_token')
    payment_url = result.get('payment_url')
    if not checkout_token or not payment_url:
        raise HTTPException(502, detail='پاسخ بازارپی فاقد checkout_token یا payment_url است')
    row = Payment(user_id=user.id, amount=body.amount, service_name=body.service_name,
                  checkout_token=checkout_token, payment_url=payment_url)
    db.add(row); db.commit(); db.refresh(row)
    redirect_base = settings.bazaarpay_redirect_url
    redirect = redirect_base + ('&' if '?' in redirect_base else '?') + urlencode({'token': checkout_token})
    separator = '&' if '?' in payment_url else '?'
    full_url = payment_url + separator + urlencode({'redirect_url': redirect})
    return {'payment_id': row.id, 'checkout_token': checkout_token, 'payment_url': full_url, 'status': row.status}

@router.get('/payments/return', response_class=HTMLResponse)
async def payment_return(token: str | None = Query(None), checkout_token: str | None = Query(None), db: Session = Depends(get_db)):
    token = token or checkout_token
    if not token:
        return HTMLResponse('<meta charset="utf-8"><h3 dir="rtl">شناسه پرداخت در آدرس بازگشت وجود ندارد.</h3>', status_code=400)
    row = db.query(Payment).filter(Payment.checkout_token == token).first()
    if not row:
        return HTMLResponse('<meta charset="utf-8"><h3 dir="rtl">تراکنش در نیازتو پیدا نشد.</h3>', status_code=404)
    try:
        result = await BazaarPay().trace(token)
        trace_status = result.get('status', 'unknown')
        row.trace_status = trace_status
        if trace_status == 'paid_committed': row.status = 'paid'
        elif trace_status == 'paid_not_committed': row.status = 'awaiting_commit'
        elif trace_status in ('unpaid',): row.status = 'pending'
        elif trace_status in ('refunded', 'paid_not_committed_refunded', 'timed_out', 'invalid_token'): row.status = trace_status
        db.commit()
        labels = {'paid_committed':'پرداخت با موفقیت نهایی شد', 'paid_not_committed':'پرداخت انجام شده؛ در انتظار ثبت نهایی خدمت', 'unpaid':'پرداخت هنوز نهایی نشده است', 'refunded':'مبلغ بازگردانده شده است', 'timed_out':'مهلت پرداخت تمام شده است', 'invalid_token':'توکن پرداخت نامعتبر است'}
        message = labels.get(trace_status, 'وضعیت پرداخت: ' + str(trace_status))
    except IntegrationError as exc:
        message = 'بررسی پرداخت موقتاً ممکن نیست. از داخل برنامه وضعیت تراکنش را دوباره بررسی کنید.'
    return HTMLResponse(f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:tahoma;background:#10151c;color:#fff;display:grid;place-items:center;min-height:90vh"><main style="background:#1b2430;padding:28px;border-radius:18px;text-align:center;max-width:440px"><h2>نیازتو</h2><p>{message}</p><p>به برنامه نیازتو برگردید و وضعیت سفارش را بررسی کنید.</p></main></body></html>''')

@router.get('/payments/{payment_id}')
async def payment_status(payment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(Payment).filter(Payment.id == payment_id, Payment.user_id == user.id).first()
    if not row: raise HTTPException(404, detail='پرداخت پیدا نشد')
    # Trace is authoritative; a browser redirect alone never marks a payment as paid.
    try:
        result = await BazaarPay().trace(row.checkout_token)
        row.trace_status = result.get('status', row.trace_status)
        if row.trace_status == 'paid_committed': row.status = 'paid'
        elif row.trace_status == 'paid_not_committed': row.status = 'awaiting_commit'
        elif row.trace_status in ('refunded','paid_not_committed_refunded','timed_out','invalid_token'): row.status = row.trace_status
        if row.status == 'paid': credit_wallet_for_payment(db, row)
        db.commit()
    except IntegrationError:
        pass
    return {'payment_id': row.id, 'amount': row.amount, 'service_name': row.service_name, 'status': row.status, 'trace_status': row.trace_status}

@router.post('/payments/{payment_id}/commit')
async def commit_payment(payment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(Payment).filter(Payment.id == payment_id, Payment.user_id == user.id).with_for_update().first()
    if not row: raise HTTPException(404, detail='پرداخت پیدا نشد')
    if row.status == 'paid':
        credit_wallet_for_payment(db, row); db.commit()
        return {'payment_id': row.id, 'status': 'paid', 'already_committed': True}
    try:
        trace = await BazaarPay().trace(row.checkout_token)
        current = trace.get('status')
        row.trace_status = current
        if current == 'paid_committed':
            row.status = 'paid'; credit_wallet_for_payment(db, row); db.commit()
            return {'payment_id': row.id, 'status':'paid'}
        if current != 'paid_not_committed':
            db.commit(); raise HTTPException(409, detail=f'پرداخت قابل نهایی‌سازی نیست: {current}')
        await BazaarPay().commit(row.checkout_token)
        # Confirm after commit to make retries safe.
        verify = await BazaarPay().trace(row.checkout_token)
        if verify.get('status') != 'paid_committed':
            row.status = 'commit_pending'; row.trace_status = verify.get('status', 'unknown'); db.commit()
            raise HTTPException(503, detail='درخواست ثبت نهایی ارسال شد؛ وضعیت هنوز قطعی نیست، دوباره استعلام کنید')
        row.status = 'paid'; row.trace_status = 'paid_committed'; credit_wallet_for_payment(db, row); db.commit()
        return {'payment_id': row.id, 'status':'paid'}
    except IntegrationError as exc:
        db.rollback(); raise HTTPException(502, detail=str(exc))
