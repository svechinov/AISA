from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/ai_biz_os"
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_NAME: str = "AI Biz OS"
    APP_ENV: str = "dev"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
