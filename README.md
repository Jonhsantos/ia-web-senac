# Assistente Automotivo

API REST de perguntas e respostas sobre veículos, construída com **FastAPI** e **Google Gemini**, usando arquivos Markdown locais como base de conhecimento.

A regra principal do projeto é simples: **a IA responde apenas com o que está nos arquivos `.md` da pasta `knowledge/`**. Se a informação não estiver lá, a API devolve:

```text
Não encontrei essa informação na base de conhecimento disponível.
```

---

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
- Respostas sempre baseadas no contexto enviado, com nome do arquivo de origem no campo `source`.
- Saída estruturada em JSON validada pelo próprio modelo (schema `answer` + `source`).
- Recarga da base sem reiniciar a aplicação (`POST /reload`).
- Tratamento de erros com mensagens claras e tipagem completa (Pydantic + Type Hints).
- Documentação interativa automática em `/docs`.

---

## Instalação

Requisitos: Python 3.10 ou superior.

```bash
# 1. Clone/entre na pasta do projeto
cd ia-web-senac

# 2. Crie o ambiente virtual (Windows)
python -m venv .venv
.venv\Scripts\activate

# 2. Alternativa no Linux/macOS
python3 -m venv .venv
source .venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt
```

---

## Configuração do `.env`

A chave do Gemini **nunca** deve ir no código. Crie um arquivo `.env` na raiz do projeto:

```bash
copy .env.example .env     # Windows
cp .env.example .env       # Linux/macOS
```

Depois edite `.env` e informe sua chave:

```env
GEMINI_API_KEY=sua_chave_aqui
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_DOCUMENTS=4
```

A chave é obtida gratuitamente em [Google AI Studio](https://aistudio.google.com/app/apikey).

Variáveis disponíveis:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `GEMINI_API_KEY` | vazio | Chave da API do Gemini. Obrigatória para o `/chat`. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo usado pelo serviço. |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Tempo limite de resposta do modelo. |
| `GEMINI_MAX_DOCUMENTS` | `4` | Máximo de documentos enviados como contexto. |
| `APP_NAME` | `Assistente Automotivo` | Nome exibido em `GET /`. |
| `APP_VERSION` | `1.0.0` | Versão exibida em `GET /`. |
| `FALLBACK_ANSWER` | frase padrão | Resposta usada quando a base não contém a informação. |
| `KNOWLEDGE_DIR` | `./knowledge` | Pasta dos arquivos Markdown. |

> O `.env` já está no `.gitignore`. Envie apenas o `.env.example` para o repositório.

---

## Executando a API

```bash
# com recarga automática ao editar o código
uvicorn app.main:app --reload

# ou pela própria aplicação
python -m app.main
```

A API sobe em `http://127.0.0.1:8000`.

- Documentação Swagger: <http://127.0.0.1:8000/docs>
- Documentação ReDoc: <http://127.0.0.1:8000/redoc>

No log de inicialização você verá a base sendo carregada:

```text
2026-01-01 12:00:00 | INFO | app.knowledge_loader | Base de conhecimento carregada: 4 documento(s), 9144 caracteres
2026-01-01 12:00:00 | INFO | app.main | Assistente Automotivo v1.0.0 iniciado
```

---

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Nome e versão da API. |
| `GET` | `/health` | Verifica se a API está online. |
| `POST` | `/chat` | Responde uma pergunta usando a base de conhecimento. |
| `GET` | `/knowledge` | Lista os documentos carregados em memória. |
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

### `GET /knowledge`

```json
{
  "documents": 3,
  "sources": ["volkswagen_golf.md", "volkswagen_jetta.md", "volkswagen_polo.md"],
  "total_chars": 66809,
  "gemini_configured": true
}
```

### `POST /reload`

```json
{
  "documents": 3,
  "sources": ["volkswagen_golf.md", "volkswagen_jetta.md", "volkswagen_polo.md"],
  "total_chars": 66809,
  "gemini_configured": true
}
```

### Erros

| Código | Situação |
| --- | --- |
| `422` | Pergunta vazia ou com menos de 3 caracteres. |
| `503` | `GEMINI_API_KEY` não configurada, pasta `knowledge/` vazia ou falha na API do Gemini. |
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

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"question\": \"Qual é a capacidade do tanque do Volkswagen Polo?\"}"
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"question\": \"Qual é a potência do motor do Jetta?\"}"
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"question\": \"Qual é a gama de motores a gasolina do Golf?\"}"
curl http://127.0.0.1:8000/knowledge
curl -X POST http://127.0.0.1:8000/reload
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
│   ├── routes.py            # Endpoints (/, /health, /chat, /knowledge, /reload)
│   ├── models.py            # Schemas de entrada e saída (Pydantic)
│   ├── gemini_service.py    # Integração com o Google Gemini + prompt e schema
│   └── knowledge_loader.py  # Leitura dos .md, seleção de documentos e contexto
│
├── knowledge/               # Base de conhecimento (adicione seus .md aqui)
│   ├── volkswagen_golf.md
│   ├── volkswagen_jetta.md
│   └── volkswagen_polo.md
│
├── .env.example             # Modelo de configuração (sem a chave real)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Como a base de conhecimento é usada

1. **Carga** (`knowledge_loader.load`): o `lifespan` do FastAPI lê todos os `.md` de `knowledge/` na inicialização e guarda os documentos em memória. Arquivos vazios ou ilegíveis são ignorados com aviso no log.
2. **Seleção** (`KnowledgeBase.select`): cada documento vira um conjunto de termos normalizados (sem acentos, sem palavras muito comuns). A pontuação soma os termos em comum e ganha um bônus quando o nome do veículo citado na pergunta aparece no documento. Se a pergunta citar um veículo, só entram no contexto os documentos do mesmo nível de relevância.
3. **Contexto** (`KnowledgeBase.build_context`): os documentos selecionados são enviados ao modelo delimitados por `[DOCUMENTO N]` e `Fonte: <arquivo.md>`, com limite de 12.000 caracteres por arquivo.
4. **Resposta** (`GeminiService.ask`): o modelo recebe instrução de responder só com base no contexto e devolver JSON (`answer`, `source`). A temperatura é baixa (`0.1`) para reduzir invenções.
5. **Validação** (`GeminiService._parse_response`): o JSON é lido tolerando cercas de código do Markdown. Se a resposta vier vazia ou fora do formato, ou se o modelo já tiver devolvido a frase de fallback, a API substitui pela resposta padrão e zera o campo `source`.

---

## Adicionando novos veículos

Basta soltar um novo arquivo `.md` em `knowledge/`. **Nenhuma alteração de código é necessária.**

```markdown
# Nome do veículo

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

- O primeiro `# Título` define o nome do veículo usado na seleção de documentos (ex.: `# Volkswagen Polo`).
- Seções sugeridas: Motor, Consumo, Capacidade do tanque, Troca de óleo, Revisões, Manutenção, Itens de segurança, Problemas comuns, Equipamentos, Informações do fabricante.
- Prefira listas com valores numéricos e unidades claras (`km`, `meses`, `litros`, `cv`, `psi`), o que melhora a precisão das respostas.

---

## Solução de problemas

**`503 - GEMINI_API_KEY não configurada`**
Crie o `.env` na raiz do projeto com `GEMINI_API_KEY=sua_chave` e reinicie a API.

**`503 - Nenhum arquivo Markdown foi encontrado`**
A pasta `knowledge/` está vazia ou `KNOWLEDGE_DIR` aponta para outro caminho. Confirme com `GET /knowledge`.

**A API responde a frase de fallback para tudo**
O modelo não encontrou a informação no contexto. Confirme que a pergunta usa termos presentes no `.md` (por exemplo "óleo" em vez de "lubrificante da motorização") e confira o `source` devolvido em respostas que funcionam.

**Respostas com acentos estranhos ou caracteres quebrados**
Verifique a codificação do arquivo: deve ser UTF-8 (o loader lê com `encoding="utf-8"`).

**Trocar de modelo**
Altere `GEMINI_MODEL` no `.env` (por exemplo `gemini-2.5-pro`) e reinicie a aplicação.