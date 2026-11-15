import httpx
from app.config import settings

class IntegrationError(Exception):
    pass

async def sms_send_verify(mobile: str, code: str):
    if not settings.smsir_api_key or not settings.smsir_template_id:
        raise IntegrationError('SMS.ir تنظیم نشده است؛ SMSIR_API_KEY و SMSIR_TEMPLATE_ID را در backend/.env وارد کنید')
    payload = {"mobile": mobile, "templateId": settings.smsir_template_id,
               "parameters": [{"name": settings.smsir_otp_parameter, "value": code}]}
    headers = {"Content-Type": "application/json", "Accept": "application/json", "x-api-key": settings.smsir_api_key}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post('https://api.sms.ir/v1/send/verify', json=payload, headers=headers)
    try: data = response.json()
    except Exception: data = {"message": response.text[:300]}
    if response.is_error or data.get('status') not in (1, '1', True):
        raise IntegrationError(f"ارسال پیامک ناموفق بود: {data.get('message', response.status_code)}")
    return data

class BazaarPay:
    def __init__(self):
        self.base = settings.bazaarpay_api_base.rstrip('/')
        self.path = settings.bazaarpay_api_path.strip('/')
        self.headers = {"Content-Type": "application/json", "User-Agent": "Niyazeto/1.0"}
        if settings.bazaarpay_auth_token:
            self.headers['Authorization'] = f"Token {settings.bazaarpay_auth_token}"

    async def post(self, endpoint: str, payload: dict):
        url = f"{self.base}/{self.path}/{endpoint.strip('/')}/"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self.headers)
        if response.status_code not in (200, 201, 202, 204):
            raise IntegrationError(f"بازارپی خطا داد ({response.status_code}): {response.text[:400]}")
        return response.json() if response.content else {}

    async def init(self, amount: int, destination: str, service_name: str):
        return await self.post('checkout/init', {"amount": amount, "destination": destination, "service_name": service_name})

    async def trace(self, checkout_token: str):
        return await self.post('trace', {"checkout_token": checkout_token})

    async def commit(self, checkout_token: str):
        return await self.post('commit', {"checkout_token": checkout_token})
