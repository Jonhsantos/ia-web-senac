"""Modelos de dados (Pydantic) used no contrato da API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    """Corpo da requisição ``POST /chat``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"question": "Qual o combustível recomendado para o fit?"}
        }
    )

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Pergunta a ser respondida com base nos arquivos Markdown.",
    )

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A pergunta não pode ser vazia.")
        return cleaned


class ChatResponse(BaseModel):
    """Resposta de ``POST /chat``."""

    answer: str = Field(..., description="Resposta baseada na base de conhecimento.")
    source: str = Field(
        default="",
        description="Arquivo Markdown usado como fonte (vazio se não houver).",
    )


class AppInfoResponse(BaseModel):
    """Resposta de ``GET /``."""

    name: str
    version: str


class HealthResponse(BaseModel):
    """Resposta de ``GET /health``."""

    status: str = "online"


class KnowledgeStatusResponse(BaseModel):
    """Resposta de ``GET /knowledge`` e ``POST /reload``."""

    documents: int = Field(..., description="Quantidade de arquivos Markdown carregados.")
    sources: list[str] = Field(..., description="Nomes dos arquivos carregados.")
    total_chars: int = Field(..., description="Total de caracteres carregados em memória.")
    gemini_configured: bool = Field(..., description="Indica se a GEMINI_API_KEY está definida.")


class ErrorResponse(BaseModel):
    """Formato padrão de erro da API."""

    detail: str