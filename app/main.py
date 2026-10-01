"""Ponto de entrada da API do Assistente Automotivo.

Na inicialização (lifespan) a aplicação lê todos os arquivos `.md` da pasta
`knowledge/` e os mantém em memória para uso como contexto do Gemini.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.gemini_service import GeminiService, GeminiServiceError
from app.knowledge_loader import KnowledgeBase
from app.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Carrega a base de conhecimento antes de receber requisições."""
    settings = get_settings()

    knowledge_base = KnowledgeBase(settings.knowledge_dir)
    documents = knowledge_base.load()

    application.state.settings = settings
    application.state.knowledge_base = knowledge_base
    application.state.gemini_service = GeminiService(settings, knowledge_base)

    logger.info("%s v%s iniciado", settings.app_name, settings.app_version)
    logger.info("Documentos disponíveis: %d", documents)
    if not settings.has_gemini_key:
        logger.warning(
            "GEMINI_API_KEY não encontrada. O endpoint /chat retornará erro até "
            "a chave ser definida no arquivo .env."
        )

    yield

    logger.info("Aplicação encerrada")


def create_app() -> FastAPI:
    """Cria e configura a instância do FastAPI."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "API de perguntas e respostas sobre veículos, usando arquivos Markdown "
            "locais como base de conhecimento e o Google Gemini como modelo."
        ),
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)

    @application.exception_handler(GeminiServiceError)
    async def gemini_error_handler(
        _request: Request, exc: GeminiServiceError
    ) -> JSONResponse:
        """Erros do Gemini viram respostas 503 com mensagem legível."""
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )

    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)