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
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from google import genai
from google.genai import errors, types

from app.config import MAX_GEMINI_TIMEOUT_SECONDS, Settings
from app.gemini_stream import STREAM_FORMAT, StreamOutput
from app.knowledge_loader import KnowledgeBase, KnowledgeDocument

logger = logging.getLogger(__name__)

MAX_GEMINI_ATTEMPTS = 3
FALLBACK_MODELS = (
    "gemini-4-hydrogen",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemini-flash-latest",
)


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
   sendo "source" o nome do arquivo de origem (por exemplo "volkswagen_golf.md")."""

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
    async def ask(
        self, question: str, *,
        on_delta: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> GeminiAnswer:
        """Responde uma pergunta usando exclusivamente a base de conhecimento."""
        chat_id = uuid4().hex[:12]
        started_at = monotonic()
        logger.info("[chat %s] Pergunta recebida (%d caracteres).", chat_id, len(question))
        if len(self._knowledge_base) == 0:
            logger.warning("[chat %s] Resposta padrão: base de conhecimento vazia.", chat_id)
            return GeminiAnswer(answer=self._settings.fallback_answer, source="")

        logger.info("[chat %s] Selecionando documentos da base.", chat_id)
        if on_status is not None:
            on_status("searching")
        documents = self._knowledge_base.select(
            question, max_documents=self._settings.gemini_max_documents
        )
        context = self._knowledge_base.build_context(documents)
        logger.info(
            "[chat %s] Contexto pronto (%d caracteres). Documentos: %s.",
            chat_id,
            len(context),
            ", ".join(document.source for document in documents) or "nenhum",
        )
        try:
            stream = StreamOutput(on_delta, on_status) if on_delta is not None else None
            raw_text = await self._generate(question, context, chat_id, stream)
        except GeminiServiceError:
            logger.error("[chat %s] Consulta concluída com falha em %.2f s.", chat_id, monotonic() - started_at)
            raise
        except asyncio.CancelledError:
            logger.info("[chat %s] Consulta cancelada em %.2f s.", chat_id, monotonic() - started_at)
            raise

        answer = self._parse_response(raw_text, documents)
        if self._looks_like_fallback(answer.answer):
            logger.info("[chat %s] Resposta padrão da base gerada em %.2f s.", chat_id, monotonic() - started_at)
        else:
            logger.info(
                "[chat %s] Resposta gerada em %.2f s. Fonte: %s.",
                chat_id,
                monotonic() - started_at,
                answer.source or "nenhuma",
            )
        return answer

    async def _generate(
        self, question: str, context: str, chat_id: str, stream: StreamOutput | None = None
    ) -> str:
        """Chama o modelo de forma assíncrona e devolve o texto bruto."""
        if not self.is_configured:
            logger.warning("[chat %s] Chave do Gemini ausente.", chat_id)
        client = self._get_client()
        prompt = f"CONTEXTO:\n{context}\n\nPERGUNTA DO USUÁRIO:\n{question}"

        instruction = SYSTEM_INSTRUCTION.replace(
            "{fallback}", self._settings.fallback_answer
        )
        if stream is not None:
            instruction = instruction.partition("\n7. ")[0] + "\n" + STREAM_FORMAT
        structured_config = types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        )
        text_config = types.GenerateContentConfig(system_instruction=instruction, temperature=0.1)
        models = dict.fromkeys((self._settings.gemini_model, *FALLBACK_MODELS))
        timeout = min(self._settings.gemini_timeout_seconds, MAX_GEMINI_TIMEOUT_SECONDS)

        for index, model in enumerate(models):
            config = text_config if stream is not None or model.startswith("gemma-") else structured_config
            if stream is not None and stream.on_status is not None:
                stream.on_status("fallback" if index else "consulting")
            started_at = monotonic()
            logger.info(
                "[chat %s] Consultando modelo %s (%s, %d/%d, limite de %g s).",
                chat_id,
                model,
                "fallback" if index else "principal",
                index + 1,
                len(models),
                timeout,
            )
            try:
                text = await asyncio.wait_for(
                    self._generate_with_retry(client, model, prompt, config, chat_id, stream),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                logger.warning("[chat %s] Modelo %s excedeu o limite de %g s.", chat_id, model, timeout)
                if stream is not None and stream.started:
                    raise GeminiServiceError("A resposta foi interrompida pelo limite de tempo.") from exc
                continue
            except Exception as exc:  # noqa: BLE001 - erro externo precisa ser reportado
                code = exc.code if isinstance(exc, errors.APIError) else None
                if stream is not None and stream.started:
                    logger.warning("[chat %s] Stream do modelo %s interrompido (%s).", chat_id, model, type(exc).__name__)
                    raise GeminiServiceError("A resposta foi interrompida. Tente novamente.") from exc
                if code in (404, 503):
                    logger.warning("[chat %s] Modelo %s indisponível (HTTP %d).", chat_id, model, code)
                    continue
                logger.error(
                    "[chat %s] Falha ao chamar o modelo %s (%s%s).",
                    chat_id,
                    model,
                    type(exc).__name__,
                    f", HTTP {code}" if code is not None else "",
                )
                if stream is not None:
                    raise GeminiServiceError("Não foi possível consultar o Gemini. Tente novamente.") from exc
                raise GeminiServiceError(f"Falha ao consultar o Gemini: {exc}") from exc

            if text and (config is structured_config or self._extract_json(text).get("answer")):
                logger.info("[chat %s] Modelo %s respondeu em %.2f s.", chat_id, model, monotonic() - started_at)
                return text
            logger.warning("[chat %s] Modelo %s devolveu uma resposta vazia ou inválida.", chat_id, model)

        logger.error("[chat %s] Modelos da cadeia de fallback esgotados.", chat_id)
        raise GeminiServiceError(
            "Nenhum dos modelos respondeu a tempo ou estava disponível. Tente novamente em instantes."
        )

    async def _generate_with_retry(
        self, client: genai.Client, model: str, prompt: str,
        config: types.GenerateContentConfig, chat_id: str, stream: StreamOutput | None,
    ) -> str:
        """Repete a chamada em caso de indisponibilidade temporária do Gemini."""
        attempt = 1
        while True:
            try:
                if stream is not None:
                    chunks = await client.aio.models.generate_content_stream(
                        model=model, contents=prompt, config=config
                    )
                    return await stream.consume(chunks)
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                return (response.text or "").strip()
            except errors.APIError as exc:
                if exc.code != 503 or attempt == MAX_GEMINI_ATTEMPTS or (stream and stream.started):
                    raise
                delay = 2 ** (attempt - 1)
                attempt += 1
                if stream is not None and stream.on_status is not None:
                    stream.on_status("retrying")
                logger.warning(
                    "[chat %s] Modelo %s retornou 503. Tentativa %d de %d em %d s.",
                    chat_id,
                    model,
                    attempt,
                    MAX_GEMINI_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)

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
