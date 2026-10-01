"""Integração com a API do Google Gemini.

Regra principal do projeto: a resposta deve ser construída **apenas** com o
contexto enviado (arquivos Markdown). Quando a informação não existe na base,
o serviço devolve a mensagem padrão definida em ``Settings.fallback_answer``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.config import Settings
from app.knowledge_loader import KnowledgeBase, KnowledgeDocument

logger = logging.getLogger(__name__)


class GeminiServiceError(RuntimeError):
    """Erro de integração com o Gemini (chave ausente, cota, rede, etc.)."""


@dataclass(frozen=True)
class GeminiAnswer:
    """Resposta produzida pelo modelo já normalizada."""

    answer: str
    source: str


SYSTEM_INSTRUCTION = """Você é o assistente virtual de uma assistência técnica automotiva.

Regras obrigatórias:
1. Responda SOMENTE com base no contexto fornecido, que é composto por arquivos
   Markdown de manuais de veículos. Nunca use conhecimento externo, suposições ou
   informações de memória.
2. Se a resposta não estiver contida no contexto, responda exatamente com a
   frase: "{fallback}" e nada mais.
3. Não invente especificações, valores, prazos ou nomes de peças.
4. Cite a unidade e o prazo quando o contexto informar (por exemplo km, meses,
   litros, cv, psi).
5. Se a pergunta estiver ambígua, responda com o que o contexto permitir e
   indique qual documento usou.
6. Seja objetivo e responda sempre em português do Brasil.
7. Formato de saída: devolva um JSON com as chaves "answer" e "source",
   sendo "source" o nome do arquivo de origem (por exemplo "fiat_pulse.md")."""

RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "answer": types.Schema(type=types.Type.STRING),
        "source": types.Schema(type=types.Type.STRING),
    },
    required=["answer", "source"],
)


class GeminiService:
    """Cliente do Gemini responsável por responder sobre a base de conhecimento."""

    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase) -> None:
        self._settings = settings
        self._knowledge_base = knowledge_base
        self._client: genai.Client | None = None

    # ------------------------------------------------------------------ #
    # Configuração do cliente
    # ------------------------------------------------------------------ #
    @property
    def is_configured(self) -> bool:
        return self._settings.has_gemini_key

    def _get_client(self) -> genai.Client:
        """Cria (uma única vez) o cliente do Gemini com a chave do ambiente."""
        if not self.is_configured:
            raise GeminiServiceError(
                "GEMINI_API_KEY não configurada. Defina a variável de ambiente "
                "GEMINI_API_KEY no arquivo .env."
            )
        if self._client is None:
            self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    # ------------------------------------------------------------------ #
    # Consulta à base de conhecimento
    # ------------------------------------------------------------------ #
    async def ask(self, question: str) -> GeminiAnswer:
        """Responde uma pergunta usando exclusivamente a base de conhecimento."""
        if len(self._knowledge_base) == 0:
            return GeminiAnswer(answer=self._settings.fallback_answer, source="")

        documents = self._knowledge_base.select(
            question, max_documents=self._settings.gemini_max_documents
        )
        context = self._knowledge_base.build_context(documents)
        raw_text = await self._generate(question, context)
        return self._parse_response(raw_text, documents)

    async def _generate(self, question: str, context: str) -> str:
        """Chama o modelo de forma assíncrona e devolve o texto bruto."""
        client = self._get_client()
        prompt = f"CONTEXTO:\n{context}\n\nPERGUNTA DO USUÁRIO:\n{question}"

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION.replace(
                "{fallback}", self._settings.fallback_answer
            ),
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        )

        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=prompt,
                    config=config,
                ),
                timeout=self._settings.gemini_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise GeminiServiceError(
                "Tempo limite excedido ao consultar o Gemini."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - erro externo precisa ser reportado
            logger.exception("Falha ao chamar o Gemini")
            raise GeminiServiceError(f"Falha ao consultar o Gemini: {exc}") from exc

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise GeminiServiceError("O Gemini devolveu uma resposta vazia.")
        return text

    # ------------------------------------------------------------------ #
    # Interpretação da resposta
    # ------------------------------------------------------------------ #
    def _parse_response(
        self, raw_text: str, documents: list[KnowledgeDocument]
    ) -> GeminiAnswer:
        """Converte a resposta do modelo em ``GeminiAnswer`` validada."""
        data = self._extract_json(raw_text)
        answer = str(data.get("answer", "")).strip()
        source = str(data.get("source", "")).strip()

        if not answer:
            return GeminiAnswer(answer=self._settings.fallback_answer, source="")

        # Respostas sem fundamento real no contexto são normalizadas.
        if not self._looks_like_fallback(answer):
            known_sources = {document.source for document in documents}
            if source not in known_sources:
                source = documents[0].source if documents else ""

        return GeminiAnswer(answer=answer, source=source)

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """Lê o JSON da resposta, tolerando cercas de código do Markdown."""
        candidate = raw_text.strip()
        candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
        candidate = re.sub(r"```$", "", candidate).strip()

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(candidate[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
        return {}

    def _looks_like_fallback(self, answer: str) -> bool:
        """Detecta se o modelo já devolveu a resposta de fallback."""
        fallback = self._settings.fallback_answer.strip().lower()
        normalized = answer.strip().lower()
        return normalized.startswith(fallback) or fallback in normalized