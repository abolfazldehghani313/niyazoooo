from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user
from app.config import settings
from app.jibit import (
    JibitIDEClient,
    JibitIDEError,
    normalize_digits,
    normalize_iranian_mobile,
)
from app.models import User

router = APIRouter(prefix="/identity/shahkar", tags=["شاهکار جیبیت"])


class ShahkarCheckRequest(BaseModel):
    national_code: str = Field(min_length=10, max_length=10, description="کد ملی ۱۰ رقمی")

    @field_validator("national_code", mode="before")
    @classmethod
    def normalize_national_code(cls, value):
        if value is None:
            return value
        normalized = normalize_digits(str(value)).strip()
        if not normalized.isdigit() or len(normalized) != 10:
            raise ValueError("کد ملی باید دقیقاً ۱۰ رقم باشد.")
        return normalized


def _provider_http_status(error: JibitIDEError) -> int:
    if error.code in ("nationalCode.not_valid", "mobileNumber.not_valid"):
        return 422
    if error.code in ("daily_limit.reached", "handler.too_many_requests"):
        return 429
    if error.code in ("nationalCode.black_listed", "mobileNumber.black_listed"):
        return 409
    if error.code in ("forbidden", "invalid.credentials", "jibit_not_configured"):
        return 503
    if error.status_code in (404, 500, 503, 504):
        return 503 if error.status_code != 504 else 504
    if error.status_code >= 500:
        return 502
    if error.status_code == 403:
        return 503
    return 422 if error.status_code == 400 else 502


@router.post("/check", summary="تطبیق کد ملی و شماره موبایل با شاهکار")
async def check_shahkar(
    body: ShahkarCheckRequest,
    user: User = Depends(get_current_user),
):
    """Verify the authenticated account's own mobile number against a national code.

    The mobile number is intentionally read from the authenticated user profile;
    clients cannot submit a different number for this check.
    """
    try:
        mobile_number = normalize_iranian_mobile(user.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        matched, track_id = await JibitIDEClient().match_national_code_mobile(
            body.national_code,
            mobile_number,
        )
    except JibitIDEError as exc:
        status_code = _provider_http_status(exc)
        # Do not return provider internals or credentials to the app client.
        safe_messages = {
            "jibit_not_configured": "اتصال شاهکار جیبیت در سرور تنظیم نشده است.",
            "invalid.credentials": "کلیدهای دسترسی جیبیت معتبر نیستند؛ تنظیمات سرور بررسی شود.",
            "nationalCode.not_valid": "کد ملی واردشده معتبر نیست.",
            "mobileNumber.not_valid": "شماره موبایل حساب کاربری معتبر نیست.",
            "daily_limit.reached": "سقف روزانه استعلام شاهکار به پایان رسیده است.",
            "handler.too_many_requests": "تعداد استعلام‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید.",
            "nationalCode.black_listed": "استعلام این کد ملی امکان‌پذیر نیست.",
            "mobileNumber.black_listed": "استعلام این شماره موبایل امکان‌پذیر نیست.",
            "providers.not_available": "سرویس‌دهنده شاهکار در حال حاضر در دسترس نیست.",
            "matching.unknown": "نتیجه تطبیق شاهکار در حال حاضر مشخص نیست.",
            "provider.timeout": "پاسخی از جیبیت دریافت نشد؛ کمی بعد دوباره تلاش کنید.",
            "provider.connection_error": "ارتباط با جیبیت برقرار نشد.",
        }
        message = safe_messages.get(exc.code, "استعلام شاهکار با خطا مواجه شد.")
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": message},
        ) from exc

    return {
        "matched": matched,
        "message": "کد ملی و شماره موبایل با یکدیگر تطابق دارند." if matched else "کد ملی و شماره موبایل متعلق به یک شخص نیستند.",
        "track_id": track_id,
    }
