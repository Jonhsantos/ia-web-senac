# Assistente Automotivo

API REST de perguntas e respostas sobre veículos, construída com **FastAPI** e **Google Gemini**, usando arquivos Markdown locais como base de conhecimento.

O modelo recebe trechos dos arquivos `.md` de `knowledge/` e é instruído a responder com base neles. Quando o modelo identifica que o contexto é insuficiente, a resposta padrão é:

```text
Não encontrei essa informação na base de conhecimento disponível.
```

---

O cliente web está no repositório [ia-web-senac-front](https://github.com/Jonhsantos/ia-web-senac-front).

## Índice

- [Funcionalidades](#funcionalidades)
- [Instalação](#instalação)
- [Configuração do `.env`](#configuração-do-env)
- [Executando a API](#executando-a-api)
- [Endpoints](#endpoints)
- [Exemplos de requisição](#exemplos-de-requisição)
- [Estrutura de pastas](#estrutura-de-pastas)
- [Como a base de conhecimento é usada](#como-a-base-de-conhecimento-é-usada)
- [Adicionando novos veículos](#adicionando-novos-veículos)
- [Solução de problemas](#solução-de-problemas)

---

## Funcionalidades

- Carrega automaticamente todos os arquivos `.md` de `knowledge/` na inicialização e mantém o conteúdo em memória.
- Seleciona os documentos mais relevantes para cada pergunta (por veículo citado e por termos em comum).
- Resposta em JSON ou streaming NDJSON, com o campo `source` para a fonte atribuída.
- Catálogo de veículos e perguntas sugeridas extraídos dos metadados dos manuais.
- Retry em caso de HTTP 503, fallback entre modelos e logs por pergunta.
- Recarga da base sem reiniciar a aplicação (`POST /reload`).
- Tratamento de erros com mensagens claras e tipagem completa (Pydantic + Type Hints).
- Documentação interativa automática em `/docs`.

---

## Instalação

Requisitos: Python 3.10 ou superior.

Na raiz do projeto, use o interpretador do ambiente virtual para instalar as dependências.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

**Linux ou macOS**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

---

## Configuração do `.env`

Edite o `.env` criado na raiz do backend e informe sua chave. A chave deve ficar no backend.

```env
GEMINI_API_KEY=sua_chave_aqui
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=10
GEMINI_MAX_DOCUMENTS=4
```

Você pode criar a chave no [Google AI Studio](https://aistudio.google.com/app/apikey).

Variáveis disponíveis:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `GEMINI_API_KEY` | vazio | Chave da API do Gemini, necessária nos dois endpoints de chat. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo consultado antes da lista de fallback. O `.env.example` sugere `gemini-3.1-flash-lite`. |
| `GEMINI_TIMEOUT_SECONDS` | `10` | Tempo limite por modelo, incluindo novas tentativas e esperas. Valores acima de 10 são limitados a 10 segundos. |
| `GEMINI_MAX_DOCUMENTS` | `4` | Máximo de documentos enviados como contexto. |
| `APP_NAME` | `Assistente Automotivo` | Nome exibido em `GET /`. |
| `APP_VERSION` | `1.0.0` | Versão exibida em `GET /`. |
| `FALLBACK_ANSWER` | frase padrão | Resposta usada quando a base não contém a informação. |
| `KNOWLEDGE_DIR` | `./knowledge` | Pasta dos arquivos Markdown. |
| `CORS_ORIGINS` | `["*"]` | Lista JSON de origens aceitas. Restrinja às origens do frontend em uma implantação com acesso direto à API. |

> O `.env` já está no `.gitignore`. Envie apenas o `.env.example` para o repositório.

---

## Executando a API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

No Linux ou macOS, use `./.venv/bin/python` no mesmo comando.

A API sobe em `http://127.0.0.1:8000`.

- Documentação Swagger: <http://127.0.0.1:8000/docs>
- Documentação ReDoc: <http://127.0.0.1:8000/redoc>

Mantenha esse terminal aberto para acompanhar a carga da base e os logs ao vivo.
Use o identificador `[chat <id>]` para seguir uma pergunta da seleção de
documentos à conclusão. O log registra o modelo, os retries, o fallback, a
duração e a fonte atribuída. Se a porta estiver ocupada, encerre a outra
instância ou alinhe a nova porta com `API_PROXY_TARGET` no frontend.

---

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Nome e versão da API. |
| `GET` | `/health` | Verifica se a API está online. |
| `POST` | `/chat` | Responde uma pergunta usando a base de conhecimento. |
| `POST` | `/chat/stream` | Envia a resposta em partes enquanto o modelo gera o texto. |
| `GET` | `/knowledge` | Lista os documentos, veículos e perguntas sugeridas da base. |
| `POST` | `/reload` | Recarrega a pasta `knowledge/` sem reiniciar. |

### `GET /`

```json
{
  "name": "Assistente Automotivo",
  "version": "1.0.0"
}
```

### `GET /health`

```json
{
  "status": "online"
}
```

### `POST /chat`

Request:

```json
{
  "question": "Qual é a capacidade do tanque do Volkswagen Polo?"
}
```

Response:

```json
{
  "answer": "O tanque de combustível possui capacidade de aproximadamente 49 litros, dos quais cerca de 7,5 litros correspondem à reserva.",
  "source": "volkswagen_polo.md"
}
```

Quando a informação não existe na base:

```json
{
  "answer": "Não encontrei essa informação na base de conhecimento disponível.",
  "source": ""
}
```

### `POST /chat/stream`

Recebe o mesmo JSON de `POST /chat` e envia uma linha JSON por evento
(`application/x-ndjson`).

| Evento | Campos e comportamento |
| --- | --- |
| `status` | `stage` indica `searching`, `consulting`, `retrying` ou `fallback`. |
| `delta` | `text` contém um fragmento da resposta. |
| `done` | `answer` e `source` trazem a resposta final e a fonte atribuída. |
| `error` | `detail` informa uma falha após o início do stream. O status HTTP já pode ser `200`. |

```ndjson
{"type":"status","stage":"searching"}
{"type":"status","stage":"consulting"}
{"type":"delta","text":"O tanque comporta "}
{"type":"delta","text":"aproximadamente 49 litros."}
{"type":"done","answer":"O tanque comporta aproximadamente 49 litros.","source":"volkswagen_polo.md"}
```

Cada modelo tem até 10 segundos, incluindo esperas e novas tentativas. A
consulta pode durar mais quando passa por vários modelos. O fallback ocorre
antes do primeiro fragmento. Se um modelo falhar depois disso, o stream
termina com `error` e o cliente pode manter o texto recebido. Ao desconectar,
o servidor cancela a geração.

### `GET /knowledge`

```json
{
  "documents": 8,
  "sources": ["chevrolet_onix.md", "fiat_strada.md", "honda_civic.md", "honda_fit.md", "volkswagen_golf.md", "volkswagen_jetta.md", "volkswagen_polo.md", "volkswagen_t-cross.md"],
  "total_chars": 2730612,
  "gemini_configured": true,
  "vehicles": [
    { "source": "chevrolet_onix.md", "make": "Chevrolet", "model": "Onix" },
    { "source": "fiat_strada.md", "make": "Fiat", "model": "Strada" },
    { "source": "honda_civic.md", "make": "Honda", "model": "Civic" },
    { "source": "honda_fit.md", "make": "Honda", "model": "Fit" },
    { "source": "volkswagen_golf.md", "make": "Volkswagen", "model": "Golf" },
    { "source": "volkswagen_jetta.md", "make": "Volkswagen", "model": "Jetta" },
    { "source": "volkswagen_polo.md", "make": "Volkswagen", "model": "Polo" },
    { "source": "volkswagen_t-cross.md", "make": "Volkswagen", "model": "T-Cross" }
  ],
  "suggested_questions": [
    "Qual é a capacidade do tanque do Polo?",
    "Qual é a potência do motor do Jetta?"
  ]
}
```

### `POST /reload`

Retorna o mesmo formato de `GET /knowledge` após recarregar os documentos.
Use essa rota em ambiente local ou restrito. A versão atual não implementa
autenticação na aplicação.

### Erros

| Código | Situação |
| --- | --- |
| `422` | Corpo inválido ou pergunta fora do intervalo de 3 a 1000 caracteres. |
| `503` | Base vazia ou falha no chat convencional. Em streaming, falhas após o início do fluxo chegam em um evento `error`. |
| `500` | Erro ao recarregar a base de conhecimento. |

Formato do erro:

```json
{
  "detail": "GEMINI_API_KEY não configurada. Defina a variável de ambiente GEMINI_API_KEY no arquivo .env."
}
```

---

## Exemplos de requisição

### PowerShell

```powershell
# Status
Invoke-RestMethod -Uri http://127.0.0.1:8000/ -Method Get

# Health check
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -Method Get

# Pergunta
$body = @{ question = "Qual é a capacidade do tanque do Volkswagen Polo?" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/chat -Method Post -ContentType "application/json" -Body $body

# Documentos carregados
Invoke-RestMethod -Uri http://127.0.0.1:8000/knowledge -Method Get
```

### cURL

Para ver cada evento chegar sem aguardar o fim da resposta, use `-N`.

```powershell
'{"question":"Qual a capacidade do tanque do Polo?"}' |
  curl.exe -N -H 'Content-Type: application/json' --data-binary '@-' http://127.0.0.1:8000/chat/stream
```

### Python

```python
import requests

BASE = "http://127.0.0.1:8000"

requests.get(f"{BASE}/").json()
# {'name': 'Assistente Automotivo', 'version': '1.0.0'}

perguntas = [
  "Qual é a capacidade do tanque do Volkswagen Polo?",
  "Qual é a potência do motor do Jetta?",
  "Qual é a gama de motores a gasolina do Golf?",
]
for pergunta in perguntas:
    resposta = requests.post(f"{BASE}/chat", json={"question": pergunta}).json()
    print(f"{pergunta}\n  -> {resposta['answer']}  (fonte: {resposta['source']})\n")
```

---

## Estrutura de pastas

```text
ia-web-senac/
│
├── app/
│   ├── __init__.py
│   ├── main.py              # Criação do FastAPI, lifespan e CORS
│   ├── config.py            # Configurações via .env (Pydantic Settings)
│   ├── routes.py            # Endpoints HTTP, incluindo /chat/stream
│   ├── models.py            # Schemas de entrada e saída (Pydantic)
│   ├── gemini_service.py    # Integração com o Google Gemini + prompt e schema
│   ├── gemini_stream.py     # Consumo do stream e separação de texto e fonte
│   └── knowledge_loader.py  # Leitura dos .md, seleção de documentos e contexto
│
├── knowledge/               # Base de conhecimento (adicione seus .md aqui)
│   └── *.md
│
├── .env.example             # Modelo de configuração (sem a chave real)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Como a base de conhecimento é usada

1. **Carga** (`knowledge_loader.load`): o `lifespan` do FastAPI lê todos os `.md` de `knowledge/` na inicialização e guarda os documentos em memória. Arquivos vazios ou ilegíveis são ignorados com aviso no log.
2. **Seleção** (`KnowledgeBase.select`): a pontuação considera termos normalizados em comum e nomes de veículos. Quando nenhum documento pontua, a API usa os primeiros arquivos até o limite configurado.
3. **Contexto** (`KnowledgeBase.build_context`): os documentos selecionados são enviados ao modelo delimitados por `[DOCUMENTO N]` e `Fonte: <arquivo.md>`, com limite de 12.000 caracteres por arquivo.
4. **Resposta** (`GeminiService.ask`): na rota convencional, o modelo recebe instruções para produzir JSON com `answer` e `source`. Na rota de streaming, a API separa a linha de fonte dos fragmentos NDJSON enviados ao cliente.
5. **Fonte** (`GeminiService._parse_response`): a API normaliza o resultado e pode atribuir o primeiro arquivo selecionado quando a fonte declarada é inválida. Confira o manual antes de usar a resposta para decisões de manutenção.

---

## Adicionando novos veículos

Basta soltar um novo arquivo `.md` em `knowledge/`. **Nenhuma alteração de código é necessária.**

```markdown
# Nome do veículo
<!-- vehicle: Fabricante | Modelo | Pergunta sugerida sobre o modelo? -->

## Especificações técnicas

- Fabricante: Nome do fabricante
- Tipo: Categoria do veículo

## Motor

- Motorização: Descrição da motorização
- Potência: Valor em cv ou kW

## Capacidade do tanque

- Tanque de combustível: Valor em litros

## Troca de óleo

- Intervalo: Distância ou período
- Lubrificante recomendado: Especificação do lubrificante
```

Depois recarregue a base:

```bash
curl -X POST http://127.0.0.1:8000/reload
```

Recomendações para os arquivos:

- O comentário `vehicle` define a marca, o modelo e uma pergunta sugerida opcional para o catálogo da API. Sem o comentário, o catálogo usa o título como modelo.
- O primeiro `# Título` define o nome do veículo usado na seleção de documentos (ex.: `# Volkswagen Polo`).
- Seções sugeridas: Motor, Consumo, Capacidade do tanque, Troca de óleo, Revisões, Manutenção, Itens de segurança, Problemas comuns, Equipamentos, Informações do fabricante.
- Prefira listas com valores numéricos e unidades claras (`km`, `meses`, `litros`, `cv`, `psi`), o que melhora a precisão das respostas.

---

## Solução de problemas

**`503 - GEMINI_API_KEY não configurada`**
Crie o `.env` na raiz do projeto com `GEMINI_API_KEY=sua_chave` e reinicie a API.

**`503 - Nenhum arquivo Markdown foi encontrado`**
A pasta `knowledge/` está vazia ou `KNOWLEDGE_DIR` aponta para outro caminho. Confirme com `GET /knowledge`.

**Nenhum dos modelos respondeu a tempo ou estava disponível**
Quando um modelo retorna HTTP 503, o backend faz até duas novas tentativas, com esperas de 1 e 2 segundos. As chamadas e as esperas compartilham o limite de 10 segundos por modelo. O serviço segue a ordem de `FALLBACK_MODELS` após timeout, HTTP 404 ou HTTP 503 persistente, sem repetir o modelo principal caso ele já esteja na lista.

**A API responde a frase de fallback para tudo**
O modelo não encontrou a informação no contexto. Confirme que a pergunta usa termos presentes no `.md` (por exemplo "óleo" em vez de "lubrificante da motorização") e confira o `source` devolvido em respostas que funcionam.

**Respostas com acentos estranhos ou caracteres quebrados**
Verifique a codificação do arquivo: deve ser UTF-8 (o loader lê com `encoding="utf-8"`).

**Trocar de modelo**
Altere `GEMINI_MODEL` no `.env` (por exemplo `gemini-2.5-pro`) e reinicie a aplicação.
