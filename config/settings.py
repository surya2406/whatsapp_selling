from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── LLM (Ollama via Google ADK + LiteLLM) ────────────────────────────────
    # IMPORTANT: LiteLLM reads OLLAMA_API_BASE (not ollama_host) for routing.
    ollama_api_base: str = "http://localhost:11434"
    ollama_host: str = "http://localhost:11434"   # kept for backward compat
    ollama_model: str = "qwen3.5-9b"

    # ── Local agent SQLite DB ─────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./whatsapp_agent.db"

    # ── Meta Engine MySQL DB (existing WhatsApp automation DB) ────────────────
    # Optional default so tests can run without a .env file present
    meta_engine_db_url: str = "mysql+aiomysql://root:password@localhost/meta_engine_db"
    meta_engine_messages_table: str = "messages"
    meta_engine_sender_col: str = "sender"
    meta_engine_recipient_col: str = "recipient"
    meta_engine_direction_col: str = "direction"
    meta_engine_message_type_col: str = "message_type"
    meta_engine_status_col: str = "status"
    meta_engine_whatsapp_message_id_col: str = "whatsapp_message_id"
    meta_engine_job_id_col: str = "job_id"
    meta_engine_body_col: str = "content"
    meta_engine_timestamp_col: str = "created_at"
    meta_engine_processed_col: str = "is_processed"

    # Meta Engine outbound HTTP endpoint. It must accept customer_id and message.
    meta_send_api_url: str = ""
    meta_send_api_token: str = ""
    meta_send_timeout_seconds: float = 20.0

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Agent behaviour ───────────────────────────────────────────────────────
    max_conversation_history: int = 10
    profile_cache_ttl_seconds: int = 3600
    offers_cache_ttl_seconds: int = 1800
    max_recommendations: int = 2
    sentiment_gate_enabled: bool = True
    dormant_threshold_days: int = 60
    post_purchase_followup_days: int = 3

    # ── A/B testing ───────────────────────────────────────────────────────────
    ab_testing_enabled: bool = False
    ab_variant_ratio: float = 0.5


settings = Settings()
