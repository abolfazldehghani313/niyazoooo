import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import OTPRequest, OTPVerify, TokenResponse
from app.auth import create_access_token
from app.services import sms_send_verify, IntegrationError

router = APIRouter(prefix="/auth", tags=["احراز هویت"])
# فقط برای تست محلی؛ با خاموش شدن سرور کدها پاک می‌شوند.
_otp_store: dict[str, tuple[str, datetime]] = {}

def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone.strip() if ch.isdigit() or ch == "+")

@router.post("/request-otp")
async def request_otp(body: OTPRequest):
    phone = normalize_phone(body.phone)
    if len(phone) < 10:
        raise HTTPException(status_code=422, detail="شماره موبایل معتبر نیست")
    code = f"{secrets.randbelow(1_000_000):06d}"
    _otp_store[phone] = (code, datetime.now(timezone.utc) + timedelta(seconds=settings.otp_expire_seconds))
    if settings.dev_otp_mode:
        print(f"[NIYAZETO DEV OTP] {phone}: {code}", flush=True)
        return {"message": "کد آزمایشی در ترمینال VS Code چاپ شد", "dev_mode": True}
    try:
        result = await sms_send_verify(phone, code)
        return {"message": "کد تأیید ارسال شد", "dev_mode": False, "message_id": (result.get("data") or {}).get("messageId")}
    except IntegrationError as exc:
        _otp_store.pop(phone, None)
        raise HTTPException(status_code=502, detail=str(exc))

@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(body: OTPVerify, db: Session = Depends(get_db)):
    phone = normalize_phone(body.phone)
    saved = _otp_store.get(phone)
    if not saved or saved[0] != body.code or saved[1] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="کد تأیید اشتباه است یا منقضی شده است")
    _otp_store.pop(phone, None)
    user = db.query(User).filter(User.phone == phone).first()
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id, phone=user.phone)
