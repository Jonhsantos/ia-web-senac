"""Carregamento da base de conhecimento a partir de arquivos Markdown locais.

A base de conhecimento é lida uma única vez, na inicialização da aplicação, e
mantida em memória. Novos arquivos `.md` podem ser adicionados a qualquer
momento e recarregados sem alterar o código (via `POST /reload`).
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Limite de caracteres por documento enviado ao modelo, para respeitar a
# janela de contexto da API sem perder as seções mais importantes.
MAX_CHARS_PER_DOCUMENT = 12_000

# Bônus de relevância aplicado quando a pergunta cita o nome do veículo.
VEHICLE_MATCH_BONUS = 5

# Palavras muito comuns em português, removidas antes do cálculo de relevância.
_STOP_WORDS: frozenset[str] = frozenset(
    """
    a o e de da do das dos em no na nos nas um uma uns umas para por com sem
    que se ao aos as os the of and or is are was were be been
    qual quais quanto como quando onde quem qualquer isto isso aquilo sobre
    info informacao informacoes me diga fale quero saber precisa pode poderia
    favor obrigado obrigada seu sua aqui esse essa este esta
    """.split()
)


@dataclass(frozen=True)
class KnowledgeDocument:
    """Um arquivo Markdown da base de conhecimento."""

    source: str
    """Nome do arquivo de origem, por exemplo ``volkswagen_gol.md``."""

    title: str
    """Título do documento (primeiro heading ou nome do arquivo)."""

    content: str
    """Conteúdo bruto do arquivo."""

    vehicle: str
    """Nome do veículo identificado a partir do título, usado na seleção."""

    terms: frozenset[str] = field(default_factory=frozenset)
    """Termos normalizados usados para ranquear o documento por relevância."""

    @property
    def size_in_chars(self) -> int:
        return len(self.content)

    def excerpt(self) -> str:
        """Conteúdo enviado ao modelo, limitado por ``MAX_CHARS_PER_DOCUMENT``."""
        if self.size_in_chars <= MAX_CHARS_PER_DOCUMENT:
            return self.content
        return self.content[:MAX_CHARS_PER_DOCUMENT].rstrip() + "\n\n[conteúdo truncado]"


class KnowledgeBase:
    """Base de conhecimento em memória, carregada a partir da pasta ``knowledge``."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._documents: list[KnowledgeDocument] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Propriedades
    # ------------------------------------------------------------------ #
    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def documents(self) -> list[KnowledgeDocument]:
        return list(self._documents)

    def __len__(self) -> int:
        return len(self._documents)

    @property
    def sources(self) -> list[str]:
        return [document.source for document in self._documents]

    @property
    def total_chars(self) -> int:
        return sum(document.size_in_chars for document in self._documents)

    # ------------------------------------------------------------------ #
    # Carga / recarga
    # ------------------------------------------------------------------ #
    def load(self) -> int:
        """Lê todos os ``.md`` da pasta e devolve a quantidade carregada."""
        with self._lock:
            self._documents = self._read_all()
        logger.info(
            "Base de conhecimento carregada: %d documento(s), %d caracteres",
            len(self._documents),
            self.total_chars,
        )
        return len(self._documents)

    def reload(self) -> int:
        """Recarrega a base de conhecimento sem reiniciar a aplicação."""
        logger.info("Recarregando base de conhecimento de %s", self._directory)
        return self.load()

    def _read_all(self) -> list[KnowledgeDocument]:
        if not self._directory.is_dir():
            logger.warning(
                "Pasta de conhecimento não encontrada: %s (criando...)", self._directory
            )
            self._directory.mkdir(parents=True, exist_ok=True)
            return []

        documents: list[KnowledgeDocument] = []
        for path in sorted(self._directory.glob("*.md")):
            document = self._read_file(path)
            if document is not None:
                documents.append(document)

        skipped = len(list(self._directory.glob("*.md"))) - len(documents)
        if skipped:
            logger.warning("%d arquivo(s) .md ignorado(s) por estarem vazios", skipped)
        return documents

    def _read_file(self, path: Path) -> KnowledgeDocument | None:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Não foi possível ler %s: %s", path.name, exc)
            return None

        cleaned = content.strip()
        if not cleaned:
            logger.warning("Arquivo vazio ignorado: %s", path.name)
            return None

        title = self._extract_title(cleaned, path.stem)
        return KnowledgeDocument(
            source=path.name,
            title=title,
            content=cleaned,
            vehicle=self._normalize(self._extract_vehicle(title)),
            terms=self._extract_terms(f"{title}\n{cleaned}"),
        )

    # ------------------------------------------------------------------ #
    # Seleção de documentos
    # ------------------------------------------------------------------ #
    def select(self, question: str, max_documents: int = 4) -> list[KnowledgeDocument]:
        """Retorna os documentos mais relevantes para a pergunta.

        Se nenhum documento pontuar, devolve todos (limitado por
        ``max_documents``) para que o modelo possa dizer que não sabe.
        """
        if not self._documents:
            return []

        query_terms = self._extract_terms(question)
        if not query_terms:
            return self._documents[:max_documents]

        normalized_question = self._normalize(question)
        scored: list[tuple[int, str, KnowledgeDocument]] = []
        for document in self._documents:
            score = len(query_terms & document.terms)
            # Bônus quando o nome do veículo citado na pergunta aparece no documento.
            if document.vehicle and document.vehicle in normalized_question:
                score += 5
            scored.append((score, document.source, document))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        matches = [document for score, _, document in scored if score > 0]
        if not matches:
            return self._documents[:max_documents]

        # Quando a pergunta cita um veículo, mantém apenas os documentos do mesmo
        # nível de relevância para não poluir o contexto com outros modelos.
        if scored[0][0] >= VEHICLE_MATCH_BONUS:
            top_score = scored[0][0]
            matches = [document for score, _, document in scored if score == top_score]

        return matches[:max_documents]

    def build_context(self, documents: list[KnowledgeDocument]) -> str:
        """Monta o contexto enviado ao modelo, delimitando cada documento."""
        blocks: list[str] = []
        for index, document in enumerate(documents, start=1):
            blocks.append(
                f"[DOCUMENTO {index}]\nFonte: {document.source}\n"
                f"Veículo: {document.title}\n\n{document.excerpt()}"
            )
        return "\n\n---\n\n".join(blocks)

    # ------------------------------------------------------------------ #
    # Utilitários de texto
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_title(content: str, fallback: str) -> str:
        match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
        return match.group(1).strip() if match else fallback

    @staticmethod
    def _extract_vehicle(title: str) -> str:
        """Remove o prefixo do fabricante: ``Fiat Pulse`` -> ``pulse``."""
        parts = title.split()
        return parts[-1] if len(parts) > 1 else title

    @classmethod
    def _extract_terms(cls, text: str) -> frozenset[str]:
        tokens = re.findall(r"[a-z0-9]+", cls._normalize(text))
        return frozenset(
            token for token in tokens if len(token) > 2 and token not in _STOP_WORDS
        )

    @staticmethod
    def _normalize(text: str) -> str:
        """Minúsculas e remoção de acentos, para comparar termos com segurança."""
        decomposed = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(char for char in decomposed if not unicodedata.combining(char))