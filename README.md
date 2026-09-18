# RouteMind

RouteMind é um AI Gateway assíncrono compatível com Chat Completions da OpenRouter. Ele preserva o contrato de requisição/resposta, seleciona um modelo pelo catálogo oficial e aplica uma política financeira conservadora antes da chamada.

## Recursos

- `POST /api/v1/chat/completions`, inclusive streaming SSE;
- repasse de parâmetros conhecidos e desconhecidos, exceto o namespace local `routemind`;
- catálogo de `GET /api/v1/models` com cache e limite de desatualização;
- seleção por modalidade, contexto, ferramentas, resposta estruturada e reasoning;
- somente modelos gratuitos por padrão;
- teto estimado em USD por requisição;
- modelo explícito, preferências, exclusões e fallback limitado;
- Bearer auth, rate limiting, timeouts e logs sem prompts;
- testes com mocks, sem cobranças reais.

## Contrato de compatibilidade

As referências são a documentação oficial de [Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) e do [catálogo de modelos](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

`messages` é o campo de corpo obrigatório. `model` é opcional na OpenRouter e no RouteMind. Se vier preenchido, o gateway não o troca silenciosamente: valida custo/capacidade e o usa ou retorna erro. Se omitido, faz a seleção automática.

O objeto `routemind` evita colisões com campos atuais ou futuros da OpenRouter e nunca é encaminhado. Todos os outros campos JSON são repassados. A validação local se limita ao necessário para segurança/roteamento; o upstream continua sendo a autoridade para parâmetros específicos de cada modelo.

Respostas e erros do upstream não são remodelados. Isso preserva `id`, `object`, `created`, `model`, `choices`, `usage` e extensões. Em streaming, os bytes SSE e `[DONE]` são retransmitidos sem reconstrução.

## Semântica financeira

`max_cost` é um **teto estimado em USD para uma única requisição**. Não é limite mensal, saldo, preço unitário nem orçamento acumulado.

```json
{
  "free_only": true,
  "max_cost": 0,
  "currency": "USD",
  "task_type": "auto",
  "preferred_models": [],
  "excluded_models": [],
  "fallback_enabled": true
}
```

Para modelos pagos, use `free_only: false` e `max_cost > 0`. Somente USD é aceito; não há conversão implícita.

```text
custo estimado = preço_prompt × tokens_entrada_estimados
                + preço_completion × máximo_de_tokens_de_saída
                + preço_por_requisição
```

Os valores do catálogo são preços por token. A saída usa `max_completion_tokens`, depois `max_tokens`, ou `ROUTEMIND_DEFAULT_OUTPUT_TOKENS`. A entrada usa uma aproximação conservadora independente de tokenizer (bytes UTF-8 / 3).

Um modelo só é gratuito quando os componentes relevantes (`prompt`, `completion`, `request`, `image`, `audio`) são válidos e zero. Preço ausente/inválido torna o modelo inelegível. Requisições com `plugins` são recusadas pelo preflight, pois ferramentas de servidor podem ter cobrança independente não representada no preço base.

A estimativa reduz risco, mas não é garantia contábil: tokenização, cache, reasoning, mídia e preço do provedor afetam o custo real. O gateway registra a estimativa e `usage.cost` quando devolvido.

## Roteamento

1. Autentica e aplica rate limit.
2. Valida `messages` e `routemind`.
3. Infere requisitos estruturais e categoria.
4. Carrega catálogo atual ou cache ainda seguro.
5. Filtra modalidades, parâmetros, contexto, exclusões e modelo explícito.
6. Rejeita preço desconhecido e aplica modo gratuito/teto.
7. Ordena preferências, afinidade, custo total e contexto.
8. Encaminha ao escolhido.

Fallback ocorre no máximo `ROUTEMIND_MAX_FALLBACK_ATTEMPTS` vezes (padrão 2) e só para status iniciais `404`, `429`, `502` ou `503`. Nunca há retry após o início de um stream nem para erro ambíguo que possa ter sido faturado.

## Arquitetura

```text
app/
├── main.py                    # aplicação, auth e rate limit
├── api/routes.py              # proxy JSON/SSE
├── core/
│   ├── config.py
│   └── errors.py
├── schemas/routemind.py
└── services/
    ├── openrouter_client.py
    ├── model_catalog.py
    ├── task_classifier.py
    ├── model_router.py
    ├── cost_estimator.py
    └── usage_tracker.py
```

Em múltiplas réplicas, substitua cache/rate limit por Redis e envie logs a um backend central. Orçamento acumulado exige ledger transacional por usuário e não deve reutilizar `max_cost`.

## Instalação

Requer Python 3.12+.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
uvicorn app.main:app --reload
```

Docker:

```bash
docker build -t routemind .
docker run --rm -p 8000:8000 --env-file .env routemind
```

## Configuração

| Variável | Padrão | Finalidade |
|---|---:|---|
| `ROUTEMIND_OPENROUTER_API_KEY` | vazio | chave secreta do upstream |
| `ROUTEMIND_API_KEYS` | vazio | chaves cliente, separadas por vírgula; vazio só para desenvolvimento |
| `ROUTEMIND_OPENROUTER_BASE_URL` | URL oficial | upstream |
| `ROUTEMIND_CATALOG_TTL_SECONDS` | `900` | TTL do catálogo |
| `ROUTEMIND_CATALOG_MAX_STALE_SECONDS` | `3600` | stale máximo em falha |
| `ROUTEMIND_REQUEST_TIMEOUT_SECONDS` | `120` | timeout HTTP |
| `ROUTEMIND_DEFAULT_OUTPUT_TOKENS` | `1024` | reserva sem limite explícito |
| `ROUTEMIND_RATE_LIMIT_PER_MINUTE` | `60` | limite por chave/IP/processo |
| `ROUTEMIND_MAX_FALLBACK_ATTEMPTS` | `2` | tentativas totais |
| `ROUTEMIND_APP_URL` | vazio | `HTTP-Referer` opcional |
| `ROUTEMIND_APP_NAME` | `RouteMind` | `X-OpenRouter-Title` |

Nunca forneça a chave OpenRouter ao cliente. Em produção, configure chaves cliente, TLS e um secret manager.

## Exemplos

Gratuito por padrão:

```bash
curl http://localhost:8000/api/v1/chat/completions \
  -H 'Authorization: Bearer client-key-1' \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Explique APIs REST."}]}'
```

Pago, limitado a US$ 0,02 nesta requisição:

```json
{
  "messages": [{"role": "user", "content": "Analise este projeto."}],
  "max_completion_tokens": 1200,
  "routemind": {
    "free_only": false,
    "max_cost": 0.02,
    "currency": "USD",
    "preferred_models": ["provider/model"],
    "excluded_models": ["provider/blocked-model"]
  }
}
```

Cliente OpenAI, trocando apenas base URL e chave:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/api/v1", api_key="client-key-1")
response = client.chat.completions.create(
    messages=[{"role": "user", "content": "Olá"}], stream=True
)
```

## Testes

```bash
.venv/bin/pytest -q
```

Os testes usam mocks. Uma validação real pode usar uma chave e modelo gratuito, mas deve ser opt-in porque catálogo, disponibilidade e rate limits mudam.

## Limitações conhecidas

- A classificação combina conteúdo, estrutura, modalidades e recursos, mas é heurística, não um classificador semântico treinado. Use `task_type` explícito quando crítico.
- O catálogo comprova compatibilidade técnica, não qualidade objetiva. Afinidade pela descrição é apenas um sinal; benchmarks versionados são a evolução recomendada.
- Rate limit, cache e tracking são locais; implantação distribuída requer Redis/persistência.
- O custo efetivo do SSE aparece dentro do stream e ainda não é extraído pelo tracker.
- Não há orçamento acumulado, conversão cambial, cobrança, painel administrativo ou isolamento persistente de tenant.
- Somente Chat Completions e `/health` são implementados.
- Campos desconhecidos são preservados, mas só o upstream confirma suporte por modelo/provedor.

## Segurança operacional

O gateway não registra prompts, não repassa a credencial do cliente e cria a autorização upstream com o segredo do servidor. A implantação ainda deve fornecer TLS, rotação de chaves, secret manager, observabilidade com redação, limites distribuídos e política de retenção.
