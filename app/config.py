from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "dev"
    http_port: int = 8888
    admin_secret_key: str = "changeme"
    log_level: str = "INFO"

    # Gateway
    gateway_base_url: str = "https://llm.clawdy.dev"
    gateway_biz_key: str = ""

    # E2B
    e2b_api_key: str = ""
    e2b_template_id: str = "base"
    e2b_sandbox_timeout: int = 86400
    e2b_sandbox_port: int = 18789

    # S3
    aws_region: str = "us-west-2"
    s3_bucket: str = "openclaw-manager"
    s3_prefix: str = "dev/"

    # BlueBubbles
    bluebubbles_server_url: str = ""
    bluebubbles_webhook_path: str = "/bluebubbles-webhook"
    bluebubbles_password: str = ""
    forward_timeout_ms: int = 10000
    unknown_sender_callback_url: str = ""

    # Renewal
    renewal_interval_hours: int = 24
    renewal_check_minutes: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
