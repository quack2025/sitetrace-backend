from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_key: str
    supabase_anon_key: str

    # AI
    anthropic_api_key: str
    openai_api_key: str = ""

    # Email
    resend_api_key: str = ""
    resend_from_email: str = "notifications@sitetrace.ai"
    resend_from_name: str = "SiteTrace"

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    action_token_expire_hours: int = 48

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # Integrations
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_redirect_uri: str = ""
    outlook_client_id: str = ""
    outlook_client_secret: str = ""
    outlook_redirect_uri: str = ""
    cf_api_base_url: str = "https://api.contractorforeman.com/v1"

    # App
    app_base_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    poll_interval_seconds: int = 300
    confidence_threshold: float = 0.70
    max_processing_time_seconds: int = 90
    max_attachment_size_mb: int = 25

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
