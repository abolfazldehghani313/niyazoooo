"""Jibit IDE client for Shahkar national-code/mobile ownership matching.

Credentials and provider tokens are kept in process memory only. The Jibit
OpenAPI document does not define token expiry, so an access token is refreshed
only after Jibit explicitly responds with `forbidden`.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx

from app.config import settings


class JibitIDEError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


_token_cache: dict[str, str] = {"access_token": "", "refresh_token": ""}
_token_lock = asyncio.Lock()


def normalize_digits(value: str) -> str:
    """Convert Persian/Arabic-Indic digits to ASCII digits."""
    table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )
    return value.translate(table)


def normalize_iranian_mobile(value: str) -> str:
    """Convert a stored Iranian mobile number to 09xxxxxxxxx format."""
    digits = "".join(ch for ch in normalize_digits(value or "") if ch.isdigit())
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    if len(digits) != 11 or not digits.startswith("09"):
        raise ValueError("شماره موبایل ثبت‌شده در حساب کاربری معتبر نیست.")
    return digits


class JibitIDEClient:
    """Minimal async client for Jibit IDE token and Shahkar matching APIs."""

    def __init__(self) -> None:
        self.base_url = settings.jibit_api_base_url.rstrip("/")
        self.timeout = httpx.Timeout(20.0, connect=10.0)

    def _require_credentials(self) -> None:
        if not settings.jibit_ide_api_key or not settings.jibit_ide_secret_key:
            raise JibitIDEError(
                503,
                "jibit_not_configured",
                "کلیدهای Jibit IDE در فایل backend/.env تنظیم نشده‌اند.",
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], httpx.Headers]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise JibitIDEError(504, "provider.timeout", "پاسخ جیبیت در مهلت مقرر دریافت نشد.") from exc
        except httpx.RequestError as exc:
            raise JibitIDEError(502, "provider.connection_error", "ارتباط با سرویس جیبیت برقرار نشد.") from exc

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        if response.is_error:
            code = str(payload.get("code") or f"http_{response.status_code}")
            message = str(payload.get("message") or "درخواست به سرویس جیبیت ناموفق بود.")
            raise JibitIDEError(response.status_code, code, message)

        if not isinstance(payload, dict):
            raise JibitIDEError(502, "provider.invalid_response", "پاسخ دریافتی از جیبیت معتبر نیست.")
        return payload, response.headers

    async def _generate_tokens(self) -> str:
        self._require_credentials()
        payload, _ = await self._request(
            "POST",
            "/ide/v1/tokens/generate",
            json_body={
                "apiKey": settings.jibit_ide_api_key,
                "secretKey": settings.jibit_ide_secret_key,
            },
        )
        access = str(payload.get("accessToken") or "")
        refresh = str(payload.get("refreshToken") or "")
        if not access or not refresh:
            raise JibitIDEError(502, "provider.invalid_token_response", "جیبیت جفت توکن دسترسی و بازیابی را برنگرداند.")
        _token_cache["access_token"] = access
        _token_cache["refresh_token"] = refresh
        return access

    async def _access_token(self) -> str:
        self._require_credentials()
        if _token_cache["access_token"]:
            return _token_cache["access_token"]
        async with _token_lock:
            if _token_cache["access_token"]:
                return _token_cache["access_token"]
            return await self._generate_tokens()

    async def _renew_after_forbidden(self, failed_access_token: str) -> str:
        """Refresh a rejected token; regenerate credentials if refresh is rejected."""
        async with _token_lock:
            # Another request may already have refreshed the shared token.
            if _token_cache["access_token"] and _token_cache["access_token"] != failed_access_token:
                return _token_cache["access_token"]

            refresh_token = _token_cache.get("refresh_token", "")
            if refresh_token:
                try:
                    # The OpenAPI example and validation errors specify both fields.
                    payload, _ = await self._request(
                        "POST",
                        "/ide/v1/tokens/refresh",
                        json_body={
                            "accessToken": failed_access_token,
                            "refreshToken": refresh_token,
                        },
                    )
                    access = str(payload.get("accessToken") or "")
                    refresh = str(payload.get("refreshToken") or "")
                    if access and refresh:
                        _token_cache["access_token"] = access
                        _token_cache["refresh_token"] = refresh
                        return access
                except JibitIDEError:
                    # The refresh token may also have expired/revoked. Try a new pair.
                    pass

            _token_cache["access_token"] = ""
            _token_cache["refresh_token"] = ""
            return await self._generate_tokens()

    async def match_national_code_mobile(
        self,
        national_code: str,
        mobile_number: str,
    ) -> tuple[bool, str]:
        """Call the Shahkar-backed matching service; returns (matched, track_id)."""
        track_id = uuid.uuid4().hex
        access_token = await self._access_token()

        async def make_match(token: str) -> dict[str, Any]:
            result, _ = await self._request(
                "GET",
                "/ide/v1/services/matching",
                params={"nationalCode": national_code, "mobileNumber": mobile_number},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-TRACK-ID": track_id,
                    "Accept": "application/json",
                },
            )
            return result

        try:
            result = await make_match(access_token)
        except JibitIDEError as exc:
            # Only `forbidden` indicates a rejected token. A daily-limit 403 must
            # be returned as-is and must not trigger token renewal.
            if exc.status_code != 403 or exc.code != "forbidden":
                raise
            renewed_token = await self._renew_after_forbidden(access_token)
            result = await make_match(renewed_token)

        matched = result.get("matched")
        if not isinstance(matched, bool):
            raise JibitIDEError(502, "provider.invalid_matching_response", "پاسخ شاهکار فاقد فیلد معتبر matched است.")
        return matched, track_id
