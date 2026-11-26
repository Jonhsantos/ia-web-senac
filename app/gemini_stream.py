"""Consome os fragmentos do Gemini e separa a fonte do texto exibido."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass

from google.genai import types

STREAM_FORMAT = (
    "7. Escreva 'Fonte: <nome do arquivo>' na primeira linha ou 'Fonte:' se não "
    "houver fonte. A partir da segunda linha, escreva somente a resposta em texto, "
    "sem JSON e sem cercas de código."
)
SOURCE_PREFIX = "Fonte:"
MAX_SOURCE_LINE = 256


@dataclass
class StreamOutput:
    on_delta: Callable[[str], None]
    on_status: Callable[[str], None] | None = None
    started: bool = False

    async def consume(
        self, chunks: AsyncGenerator[types.GenerateContentResponse, None]
    ) -> str:
        source = ""
        header = ""
        reading_header = True
        parts: list[str] = []

        def append(text: str) -> None:
            if not text or (not self.started and not text.strip()):
                return
            self.started = True
            parts.append(text)
            self.on_delta(text)

        async with aclosing(chunks):
            async for chunk in chunks:
                part = chunk.text or ""
                if reading_header:
                    header += part
                    line, newline, body = header.partition("\n")
                    if newline and line.casefold().startswith(SOURCE_PREFIX.casefold()):
                        source = line[len(SOURCE_PREFIX):].strip()
                        part = body
                    elif not newline and (
                        SOURCE_PREFIX.casefold().startswith(header.casefold())
                        or (
                            header.casefold().startswith(SOURCE_PREFIX.casefold())
                            and len(header) <= MAX_SOURCE_LINE
                        )
                    ):
                        continue
                    else:
                        part = header
                    reading_header = False
                append(part)

        if reading_header and not header.casefold().startswith(SOURCE_PREFIX.casefold()):
            append(header)
        return json.dumps({"answer": "".join(parts), "source": source}) if parts else ""
