from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Literal
from pathlib import Path
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi import UploadFile, File, Form
from uuid import uuid4
import shutil
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.config import settings
from app.database import get_db
from app.models import User, Ad, AdCampaign, Payment
from app.services import sms_send_verify, BazaarPay, IntegrationError
from app.jibit import JibitIDEClient, JibitIDEError, normalize_digits, normalize_iranian_mobile

router = APIRouter(tags=["مدیریت سایت"])
admin_bearer = HTTPBearer(auto_error=False)

class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)

class CampaignInput(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    ad_type: Literal["banner", "interstitial"]
    image_url: str = ""
    video_url: str = ""
    media_type: Literal["image", "video"] = "image"
    target_url: str = ""
    placement: str = "home"
    is_active: bool = True
    priority: int = Field(default=1, ge=1, le=1000)
    frequency_cap: int = Field(default=3, ge=0, le=100)
    start_at: datetime | None = None
    end_at: datetime | None = None


class IntegrationConfigInput(BaseModel):
    smsir_api_key: str | None = Field(default=None, max_length=500)
    smsir_template_id: int | None = Field(default=None, ge=1)
    smsir_otp_parameter: str | None = Field(default=None, max_length=80)
    dev_otp_mode: bool | None = None
    bazaarpay_api_base: str | None = Field(default=None, max_length=500)
    bazaarpay_api_path: str | None = Field(default=None, max_length=200)
    bazaarpay_destination: str | None = Field(default=None, max_length=500)
    bazaarpay_auth_token: str | None = Field(default=None, max_length=1000)
    bazaarpay_redirect_url: str | None = Field(default=None, max_length=1000)
    jibit_api_base_url: str | None = Field(default=None, max_length=500)
    jibit_ide_api_key: str | None = Field(default=None, max_length=500)
    jibit_ide_secret_key: str | None = Field(default=None, max_length=1000)

class IntegrationTestInput(BaseModel):
    mobile: str | None = Field(default=None, max_length=30)
    national_code: str | None = Field(default=None, max_length=20)
    amount: int | None = Field(default=None, ge=1, le=1000000000)


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="ورود مدیر لازم است")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("role") != "admin":
            raise ValueError("not admin")
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="نشست مدیریت معتبر نیست")
    return True

@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "static" / "admin.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@router.post("/api/admin/login")
def admin_login(body: AdminLogin):
    if not compare_digest(body.username, settings.admin_username) or not compare_digest(body.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")
    expires = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": "admin", "role": "admin", "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return {"access_token": token, "token_type": "bearer", "expires_in": 28800}

@router.get("/api/admin/overview", dependencies=[Depends(require_admin)])
def overview(db: Session = Depends(get_db)):
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "active_users": db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0,
        "ads": db.query(func.count(Ad.id)).scalar() or 0,
        "active_ads": db.query(func.count(Ad.id)).filter(Ad.is_active.is_(True)).scalar() or 0,
        "campaigns": db.query(func.count(AdCampaign.id)).scalar() or 0,
        "active_campaigns": db.query(func.count(AdCampaign.id)).filter(AdCampaign.is_active.is_(True)).scalar() or 0,
    }

@router.get("/api/admin/users", dependencies=[Depends(require_admin)])
def users(db: Session = Depends(get_db)):
    return [{"id": u.id, "phone": u.phone, "is_active": u.is_active, "created_at": u.created_at.isoformat() if u.created_at else None, "ads_count": len(u.ads)} for u in db.query(User).order_by(User.id.desc()).limit(500).all()]

@router.patch("/api/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(user_id: int, body: dict, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(status_code=404, detail="کاربر پیدا نشد")
    if "is_active" in body: user.is_active = bool(body["is_active"])
    db.commit()
    return {"id": user.id, "is_active": user.is_active}

@router.get("/api/admin/ads", dependencies=[Depends(require_admin)])
def admin_ads(db: Session = Depends(get_db)):
    rows = db.query(Ad).order_by(Ad.id.desc()).limit(500).all()
    return [{"id": a.id, "title": a.title, "city": a.city, "category": a.category, "price": a.price, "is_active": a.is_active, "owner_phone": a.owner.phone if a.owner else "", "created_at": a.created_at.isoformat() if a.created_at else None} for a in rows]

@router.patch("/api/admin/ads/{ad_id}", dependencies=[Depends(require_admin)])
def update_ad(ad_id: int, body: dict, db: Session = Depends(get_db)):
    ad = db.get(Ad, ad_id)
    if not ad: raise HTTPException(status_code=404, detail="آگهی پیدا نشد")
    if "is_active" in body: ad.is_active = bool(body["is_active"])
    db.commit()
    return {"id": ad.id, "is_active": ad.is_active}

@router.delete("/api/admin/ads/{ad_id}", dependencies=[Depends(require_admin)])
def remove_ad(ad_id: int, db: Session = Depends(get_db)):
    ad = db.get(Ad, ad_id)
    if not ad: raise HTTPException(status_code=404, detail="آگهی پیدا نشد")
    db.delete(ad); db.commit()
    return {"deleted": True}

@router.post("/api/admin/uploads", dependencies=[Depends(require_admin)])
async def upload_campaign_media(file: UploadFile = File(...)):
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
    ext = allowed.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=415, detail="فرمت فایل پشتیبانی نمی‌شود؛ تصویر JPG/PNG/WEBP یا ویدئوی MP4/WEBM انتخاب کنید")
    data = await file.read()
    limit = 25 * 1024 * 1024 if ext in {".mp4", ".webm", ".mov"} else 8 * 1024 * 1024
    if not data or len(data) > limit:
        raise HTTPException(status_code=413, detail=f"حجم فایل باید کمتر از {limit // (1024*1024)} مگابایت باشد")
    folder = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "uploads")))
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}{ext}"
    (folder / name).write_bytes(data)
    return {"url": f"/uploads/{name}", "filename": name, "media_type": "video" if ext in {".mp4", ".webm", ".mov"} else "image", "size": len(data)}

@router.get("/api/admin/campaigns", dependencies=[Depends(require_admin)])
def campaigns(db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "ad_type": c.ad_type, "image_url": c.image_url, "video_url": c.video_url, "media_type": c.media_type, "target_url": c.target_url, "placement": c.placement, "is_active": c.is_active, "priority": c.priority, "frequency_cap": c.frequency_cap, "start_at": c.start_at.isoformat() if c.start_at else None, "end_at": c.end_at.isoformat() if c.end_at else None} for c in db.query(AdCampaign).order_by(AdCampaign.priority.desc(), AdCampaign.id.desc()).all()]

@router.post("/api/admin/campaigns", dependencies=[Depends(require_admin)])
def create_campaign(body: CampaignInput, db: Session = Depends(get_db)):
    campaign = AdCampaign(**body.model_dump())
    db.add(campaign); db.commit(); db.refresh(campaign)
    return {"id": campaign.id, "title": campaign.title}

@router.put("/api/admin/campaigns/{campaign_id}", dependencies=[Depends(require_admin)])
def edit_campaign(campaign_id: int, body: CampaignInput, db: Session = Depends(get_db)):
    campaign = db.get(AdCampaign, campaign_id)
    if not campaign: raise HTTPException(status_code=404, detail="کمپین پیدا نشد")
    for key, value in body.model_dump().items(): setattr(campaign, key, value)
    db.commit(); return {"id": campaign.id, "updated": True}

@router.delete("/api/admin/campaigns/{campaign_id}", dependencies=[Depends(require_admin)])
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(AdCampaign, campaign_id)
    if not campaign: raise HTTPException(status_code=404, detail="کمپین پیدا نشد")
    db.delete(campaign); db.commit(); return {"deleted": True}

@router.get("/api/v1/monetization/placements")
def public_placements(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.query(AdCampaign).filter(AdCampaign.is_active.is_(True)).order_by(AdCampaign.priority.desc()).all()
    result = {"banner": [], "interstitial": []}
    for c in rows:
        if c.start_at and c.start_at.replace(tzinfo=timezone.utc) > now: continue
        if c.end_at and c.end_at.replace(tzinfo=timezone.utc) < now: continue
        result[c.ad_type].append({"id": c.id, "title": c.title, "image_url": c.image_url, "video_url": c.video_url, "media_type": c.media_type, "target_url": c.target_url, "placement": c.placement, "frequency_cap": c.frequency_cap})
    return result


@router.get("/api/admin/integrations", dependencies=[Depends(require_admin)])
def integration_status():
    return {
        "smsir": {"configured": bool(settings.smsir_api_key and settings.smsir_template_id), "template_id": settings.smsir_template_id or None, "otp_parameter": settings.smsir_otp_parameter, "api_key_configured": bool(settings.smsir_api_key)},
        "bazaarpay": {"configured": bool(settings.bazaarpay_destination), "destination_configured": bool(settings.bazaarpay_destination), "destination": settings.bazaarpay_destination, "auth_token_configured": bool(settings.bazaarpay_auth_token), "api_base": settings.bazaarpay_api_base, "api_path": settings.bazaarpay_api_path, "redirect_url": settings.bazaarpay_redirect_url},
        "jibit_shahkar": {"configured": bool(settings.jibit_ide_api_key and settings.jibit_ide_secret_key), "api_key_configured": bool(settings.jibit_ide_api_key), "secret_key_configured": bool(settings.jibit_ide_secret_key), "api_base_url": settings.jibit_api_base_url},
        "dev_otp_mode": settings.dev_otp_mode
    }


_ENV_KEYS = {
    "smsir_api_key": "SMSIR_API_KEY", "smsir_template_id": "SMSIR_TEMPLATE_ID",
    "smsir_otp_parameter": "SMSIR_OTP_PARAMETER", "dev_otp_mode": "DEV_OTP_MODE",
    "bazaarpay_api_base": "BAZAARPAY_API_BASE", "bazaarpay_api_path": "BAZAARPAY_API_PATH",
    "bazaarpay_destination": "BAZAARPAY_DESTINATION", "bazaarpay_auth_token": "BAZAARPAY_AUTH_TOKEN",
    "bazaarpay_redirect_url": "BAZAARPAY_REDIRECT_URL", "jibit_api_base_url": "JIBIT_API_BASE_URL",
    "jibit_ide_api_key": "JIBIT_IDE_API_KEY", "jibit_ide_secret_key": "JIBIT_IDE_SECRET_KEY",
}


def _write_integration_env(values: dict):
    """Persist integration credentials on the backend host, never in the APK."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines()
    updates = {}
    for field, env_key in _ENV_KEYS.items():
        value = values.get(field)
        if value is None or (isinstance(value, str) and value == ""):
            continue
        if field == "smsir_template_id":
            value = str(int(value))
        elif field == "dev_otp_mode":
            value = "true" if value else "false"
        else:
            value = str(value).replace("\\", "\\\\").replace('"', '\\"')
            value = f'"{value}"'
        updates[env_key] = value
    found = set()
    out = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in found:
            out.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=str(env_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out).rstrip() + "\n")
        try: os.chmod(temp_name, 0o600)
        except OSError: pass
        os.replace(temp_name, env_path)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    # Apply immediately to this running process; restart is not required.
    for field, env_key in _ENV_KEYS.items():
        if field in values and values[field] is not None and not (isinstance(values[field], str) and values[field] == ""):
            setattr(settings, field, values[field])
    try:
        from app.jibit import _token_cache
        _token_cache["access_token"] = ""
        _token_cache["refresh_token"] = ""
    except Exception:
        pass


@router.post("/api/admin/integrations/config", dependencies=[Depends(require_admin)])
def save_integration_config(body: IntegrationConfigInput):
    values = body.model_dump(exclude_unset=True)
    # Empty secret inputs mean keep the currently stored secret, not erase it.
    _write_integration_env(values)
    return {"saved": True, "message": "تنظیمات در بک‌اند ذخیره و در همین اجرا اعمال شد."}


@router.post("/api/admin/integrations/test/{provider}", dependencies=[Depends(require_admin)])
async def test_integration(provider: str, body: IntegrationTestInput):
    if provider == "smsir":
        if not body.mobile:
            raise HTTPException(422, detail="برای تست SMS.ir شماره موبایل مقصد را وارد کنید.")
        import secrets
        code = str(secrets.randbelow(900000) + 100000)
        try:
            await sms_send_verify(body.mobile.strip(), code)
            return {"connected": True, "message": "درخواست ارسال آزمایشی با موفقیت به SMS.ir ارسال شد. دریافت پیامک را بررسی کنید."}
        except Exception as exc:
            raise HTTPException(502, detail=f"تست SMS.ir ناموفق بود: {str(exc)[:250]}")
    if provider == "jibit":
        try:
            await JibitIDEClient()._access_token()
            return {"connected": True, "message": "احراز هویت جیبیت موفق بود و توکن دسترسی دریافت شد."}
        except JibitIDEError as exc:
            raise HTTPException(502, detail=f"تست جیبیت ناموفق بود: {exc.message}")
    if provider == "bazaarpay":
        if not settings.bazaarpay_destination:
            raise HTTPException(503, detail="شناسه مقصد بازارپی را ابتدا ذخیره کنید.")
        amount = body.amount or settings.payment_min_amount
        try:
            result = await BazaarPay().init(amount, settings.bazaarpay_destination, "تست اتصال پنل مدیریت")
            if not result.get("checkout_token") or not result.get("payment_url"):
                raise IntegrationError("پاسخ بازارپی فاقد checkout_token یا payment_url است")
            return {"connected": True, "message": "ارتباط با بازارپی موفق بود؛ نشست پرداخت آزمایشی ساخته شد و پرداختی انجام نشده است."}
        except Exception as exc:
            raise HTTPException(502, detail=f"تست بازارپی ناموفق بود: {str(exc)[:250]}")
    raise HTTPException(404, detail="سرویس شناخته‌شده نیست.")

@router.get("/api/admin/payments", dependencies=[Depends(require_admin)])
def admin_payments(db: Session = Depends(get_db)):
    rows = db.query(Payment).order_by(Payment.id.desc()).limit(300).all()
    return [{"id": p.id, "user_id": p.user_id, "amount": p.amount, "service_name": p.service_name, "status": p.status, "trace_status": p.trace_status, "created_at": p.created_at.isoformat() if p.created_at else None} for p in rows]
