"""Rotas HTTP da API do Assistente Automotivo."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.config import Settings, get_settings
from app.gemini_service import GeminiService, GeminiServiceError
from app.knowledge_loader import KnowledgeBase
from app.models import (
    AppInfoResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    KnowledgeStatusResponse,
    VehicleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _knowledge_base(request: Request) -> KnowledgeBase:
    """Recupera a base de conhecimento carregada no estado da aplicação."""
    return request.app.state.knowledge_base


def _gemini_service(request: Request) -> GeminiService:
    """Recupera o serviço do Gemini injetado na aplicação."""
    return request.app.state.gemini_service


def _settings() -> Settings:
    """Configurações da aplicação (cache em processo)."""
    return get_settings()


@router.get("/", response_model=AppInfoResponse, tags=["status"])
async def root() -> AppInfoResponse:
    """Informações básicas da API."""
    settings = _settings()
    return AppInfoResponse(name=settings.app_name, version=settings.app_version)


@router.get("/health", response_model=HealthResponse, tags=["status"])
async def health() -> HealthResponse:
    """Verifica se a API está no ar."""
    return HealthResponse(status="online")


@router.get("/knowledge", response_model=KnowledgeStatusResponse, tags=["status"])
async def knowledge_status(request: Request) -> KnowledgeStatusResponse:
    """Lista os arquivos Markdown carregados em memória."""
    documents = _knowledge_base(request).documents
    return KnowledgeStatusResponse(
        documents=len(documents),
        sources=[document.source for document in documents],
        total_chars=sum(document.size_in_chars for document in documents),
        gemini_configured=_gemini_service(request).is_configured,
        vehicles=[
            VehicleResponse(source=document.source, make=document.make, model=document.model)
            for document in documents
        ],
        suggested_questions=sorted({
            document.suggested_question for document in documents if document.suggested_question
        }),
    )


@router.post("/reload", response_model=KnowledgeStatusResponse, tags=["status"])
async def reload_knowledge(request: Request) -> KnowledgeStatusResponse:
    """Recarrega a pasta ``knowledge`` sem reiniciar a aplicação."""
    base = _knowledge_base(request)
    try:
        base.reload()
    except OSError as exc:
        logger.exception("Falha ao recarregar a base de conhecimento")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao recarregar a base de conhecimento: {exc}",
        ) from exc

    return await knowledge_status(request)


@router.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    responses={
        400: {"description": "Pergunta inválida"},
        503: {"description": "Serviço de IA indisponível"},
    },
)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Responde uma pergunta usando apenas os arquivos Markdown carregados."""
    service = _gemini_service(request)
    base = _knowledge_base(request)

    if len(base) == 0:
        logger.warning("Pergunta recusada em POST /chat: base de conhecimento vazia.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nenhum arquivo Markdown foi encontrado na pasta knowledge/.",
        )

    try:
        answer = await service.ask(payload.question)
    except GeminiServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return ChatResponse(answer=answer.answer, source=answer.source)
