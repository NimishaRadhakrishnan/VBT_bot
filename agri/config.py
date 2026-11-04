"""Central settings. Every external service is optional and switched on by .env values."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---------------------------------------------------------
    database_url: str = "postgresql://agri:agri@localhost:5432/agri"

    # --- API --------------------------------------------------------------
    api_base_url: str = "http://localhost:8000"
    api_key: str = "change-me"  # channels send this in X-API-Key
    media_dir: Path = ROOT / "media"  # local stand-in for object storage

    # --- Telegram adapter -------------------------------------------------
    telegram_bot_token: str = ""
    telegram_mode: str = "polling"  # polling (laptop) | webhook (server)
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    agronomist_chat_id: str = ""  # Telegram group id for escalations

    # --- LLM (understanding, grounded answers, VLM symptom description) ---
    llm_provider: str = "none"  # gemini | anthropic | none
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    llm_timeout_s: float = 40.0

    # --- Speech -----------------------------------------------------------
    stt_provider: str = "none"  # sarvam | none
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"
    sarvam_tts_model: str = "bulbul:v3"
    tts_enabled: bool = False

    # --- Vision -----------------------------------------------------------
    crop_backend: str = "bioclip"  # bioclip | vlm | none
    bioclip_model: str = "hf-hub:imageomics/bioclip-2"
    heads_dir: Path = ROOT / "models" / "heads"
    blur_threshold: float = 60.0  # Laplacian variance; tune on real photos
    min_side_px: int = 300
    plant_threshold: float = 0.55
    crop_min_conf: float = 0.60
    crop_min_margin: float = 0.20
    disease_min_conf: float = 0.55
    disease_likely_conf: float = 0.80

    # --- Retrieval --------------------------------------------------------
    embedding_provider: str = "bge-m3"  # bge-m3 | hash (tests/dev only)
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = ""  # e.g. BAAI/bge-reranker-v2-m3 ; empty = off
    rerank_min_score: float = 0.005
    retrieval_min_score: float = 0.012  # RRF floor when no reranker
    top_k: int = 6

    # --- Conversation -----------------------------------------------------
    case_idle_days: int = 7
    max_questions: int = 2
    rate_limit_per_10min: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
