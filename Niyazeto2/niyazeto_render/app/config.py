from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Niyazeto API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./niyazeto.db"
    jwt_secret_key: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    dev_otp_mode: bool = True
    otp_expire_seconds: int = 180
    cors_origins: str = "http://localhost,http://127.0.0.1"
    admin_username: str = "abolfazl"
    admin_password: str = "1991218771"
    smsir_api_key: str = ""
    smsir_template_id: int = 0
    smsir_otp_parameter: str = "Code"
    bazaarpay_api_base: str = "https://api.bazaar-pay.ir"
    bazaarpay_api_path: str = "badje/v1"
    bazaarpay_destination: str = ""
    bazaarpay_auth_token: str = ""
    bazaarpay_redirect_url: str = "https://example.com/api/v1/payments/return"
    jibit_api_base_url: str = "https://napi.jibit.ir"
    jibit_ide_api_key: str = ""
    jibit_ide_secret_key: str = ""
    payment_min_amount: int = 1000
    payment_max_amount: int = 1000000000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

settings = Settings()
