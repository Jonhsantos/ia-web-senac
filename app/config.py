"""Configuração da aplicação via variáveis de ambiente (arquivo ``.env``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto (pasta que contém ``app/`` e ``knowledge/``).
BASE_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configurações lidas do ambiente ou do arquivo ``.env``."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API -----------------------------------------------------------
    app_name: str = Field(default="Assistente Automotivo")
    app_version: str = Field(default="1.0.0")

    # --- Google Gemini -------------------------------------------------
    gemini_api_key: str = Field(
        default="",
        description="Chave da API do Google Gemini (nunca versionar no código).",
    )
    gemini_model: str = Field(default="gemini-2.5-flash")
    gemini_timeout_seconds: float = Field(default=30.0)
    gemini_max_documents: int = Field(
        default=4,
        description="Quantidade máxima de documentos enviados como contexto por pergunta.",
    )

    # --- Base de conhecimento ------------------------------------------
    knowledge_dir: Path = Field(default=BASE_DIR / "knowledge")

    # --- CORS ----------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- Resposta padrão quando a base não contém a informação ---------
    fallback_answer: str = Field(
        default="Não encontrei essa informação na base de conhecimento disponível."
    )

    @property
    def has_gemini_key(self) -> bool:
        """Indica se a chave do Gemini foi configurada."""
        return bool(self.gemini_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve as configurações em cache (uma única instância por processo)."""
    return Settings()