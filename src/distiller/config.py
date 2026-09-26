"""Environment-driven settings for distiller.

Adapted from terpafy-ai/courier's pydantic-settings pattern. All values have
safe defaults; the default (local) extraction engine needs no API keys.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractionEngine(str, Enum):
    LOCAL = "local"
    VLM = "vlm"


class VlmProvider(str, Enum):
    GROQ = "groq"
    ANTHROPIC = "anthropic"


class ChunkProfile(str, Enum):
    GENERIC = "generic"
    BOOK = "book"
    CURATED = "curated"


# Per-provider OpenAI-compatible chat-completions endpoints and default vision
# models. Both speak the same request shape Docling's API VLM path emits.
PROVIDER_DEFAULTS: dict[VlmProvider, dict[str, str]] = {
    VlmProvider.GROQ: {
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    },
    VlmProvider.ANTHROPIC: {
        "endpoint": "https://api.anthropic.com/v1/chat/completions",
        "model": "claude-sonnet-5",
    },
}


class Settings(BaseSettings):
    """distiller configuration, loaded from environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Extraction ----------------------------------------------------------
    extraction_engine: ExtractionEngine = Field(
        default=ExtractionEngine.LOCAL, alias="EXTRACTION_ENGINE"
    )
    do_ocr: bool = Field(default=False, alias="DO_OCR")

    # --- VLM extraction ------------------------------------------------------
    vlm_provider: VlmProvider = Field(default=VlmProvider.GROQ, alias="VLM_PROVIDER")
    vlm_endpoint: str = Field(default="", alias="VLM_ENDPOINT")
    vlm_model: str = Field(default="", alias="VLM_MODEL")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # --- Chunking ------------------------------------------------------------
    default_chunk_profile: ChunkProfile = Field(
        default=ChunkProfile.BOOK, alias="DEFAULT_CHUNK_PROFILE"
    )
    max_chunk_chars: int = Field(default=2000, gt=0, alias="MAX_CHUNK_CHARS")
    filter_index_chunks: bool = Field(default=True, alias="FILTER_INDEX_CHUNKS")

    # --- Output --------------------------------------------------------------
    output_dir: str = Field(default="./output", alias="OUTPUT_DIR")

    @field_validator("vlm_endpoint")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def resolved_endpoint(self) -> str:
        """The VLM endpoint to call — explicit override or the provider default."""
        return self.vlm_endpoint or PROVIDER_DEFAULTS[self.vlm_provider]["endpoint"]

    def resolved_model(self) -> str:
        """The VLM model to request — explicit override or the provider default."""
        return self.vlm_model or PROVIDER_DEFAULTS[self.vlm_provider]["model"]

    def resolved_api_key(self) -> str:
        """The API key for the selected provider (empty if unset)."""
        if self.vlm_provider is VlmProvider.GROQ:
            return self.groq_api_key
        return self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
