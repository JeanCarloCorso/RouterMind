# RouteMind

RouteMind é um AI Gateway assíncrono compatível com Chat Completions da OpenRouter. Ele preserva o contrato de requisição/resposta, seleciona um modelo pelo catálogo oficial e aplica uma política financeira conservadora antes da chamada.

Cada usuário possui uma conta própria, cadastra sua própria credencial OpenRouter e gera chaves RouteMind independentes para consumir a API. A credencial OpenRouter utilizada em uma chamada é sempre a pertencente ao proprietário da chave RouteMind apresentada.

## Início rápido

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Copie o segredo gerado para `ROUTEMIND_SECRET_KEY` no `.env` e execute:

```bash
uvicorn app.main:app --reload
```

Depois:

1. Abra `http://localhost:8000/register`.
2. Crie sua conta com uma senha de pelo menos 12 caracteres.
3. Cadastre sua chave pessoal da OpenRouter no painel.
4. Gere uma chave RouteMind e copie-a imediatamente; ela será exibida uma única vez.
5. Use essa chave como Bearer token em `POST /api/v1/chat/completions`.

## Recursos

- `POST /api/v1/chat/completions`, inclusive streaming SSE;
- repasse de parâmetros conhecidos e desconhecidos, exceto o namespace local `routemind`;
- catálogo de `GET /api/v1/models` com cache e limite de desatualização;
- seleção por modalidade, contexto, ferramentas, resposta estruturada e reasoning;
- somente modelos gratuitos por padrão;
- teto estimado em USD por requisição;
- modelo explícito, preferências, exclusões e fallback limitado;
- Bearer auth, rate limiting, timeouts e logs sem prompts;
- contas independentes com cadastro, login, sessão segura e proteção CSRF;
- painel web para cadastrar a chave pessoal OpenRouter e administrar chaves RouteMind;
- chaves RouteMind armazenadas somente como HMAC e chaves OpenRouter criptografadas em repouso;
- testes com mocks, sem cobranças reais.

## Contrato de compatibilidade

As referências são a documentação oficial de [Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) e do [catálogo de modelos](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

`messages` é o campo de corpo obrigatório. `model` é opcional na OpenRouter e no RouteMind. Se vier preenchido, o gateway não o troca silenciosamente: valida custo/capacidade e o usa ou retorna erro. Se omitido, faz a seleção automática.

O objeto `routemind` evita colisões com campos atuais ou futuros da OpenRouter e nunca é encaminhado. Todos os outros campos JSON são repassados. A validação local se limita ao necessário para segurança/roteamento; o upstream continua sendo a autoridade para parâmetros específicos de cada modelo.

### Isolamento por usuário

Cada conta cadastra sua própria chave OpenRouter e pode emitir várias chaves RouteMind no formato `rm_live_...`. Ao receber uma chamada, o gateway calcula o HMAC da chave RouteMind, identifica seu proprietário e descriptografa somente a chave OpenRouter dessa conta. Portanto, uma chave RouteMind de Alice nunca consulta nem utiliza a credencial de Bob.

A chave RouteMind completa é exibida uma única vez e não pode ser recuperada do banco. A chave OpenRouter é criptografada com Fernet usando material derivado de `ROUTEMIND_SECRET_KEY` e nunca volta a ser exibida no painel.

```text
rm_live_... → HMAC indexado → usuário → chave OpenRouter descriptografada → OpenRouter
```

O token `rm_live_...` nunca é encaminhado à OpenRouter. A chave OpenRouter nunca é devolvida pela API nem pelo painel.

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

Limites de saída muito pequenos podem ser consumidos por tokens de raciocínio e resultar em `content: null`. O RouteMind preserva o limite solicitado e não repete uma resposta HTTP `200`, pois aumentar o limite ou refazer uma geração bem-sucedida poderia quebrar compatibilidade e duplicar custo. Para respostas textuais curtas, prefira pelo menos 64 tokens; modelos de raciocínio podem exigir mais.

## Roteamento

1. Autentica e aplica rate limit.
2. Valida `messages` e `routemind`.
3. Infere requisitos estruturais e categoria.
4. Carrega catálogo atual ou cache ainda seguro.
5. Filtra modalidades, parâmetros, contexto, exclusões e modelo explícito.
6. Rejeita preço desconhecido e aplica modo gratuito/teto.
7. Ordena preferências, afinidade, custo total e contexto.
8. Encaminha ao escolhido.

Fallback ocorre no máximo `ROUTEMIND_MAX_FALLBACK_ATTEMPTS` vezes (padrão 2) e só para rejeições anteriores à geração (`403`, `404`, `429`, `502` ou `503`). No modo gratuito automático, `openrouter/free` é reservado como candidato de recuperação. Um modelo que responde `403` é colocado em quarentena local por 15 minutos para evitar repetição imediata. Modelos solicitados explicitamente não são substituídos. Nunca há retry após o início de um stream nem para erro ambíguo que possa ter sido faturado.

## Arquitetura

```text
app/
├── main.py                    # aplicação, auth e rate limit
├── web.py                     # cadastro, login e painel HTML
├── api/routes.py              # proxy JSON/SSE
├── core/
│   ├── config.py
│   └── errors.py
├── schemas/routemind.py
└── services/
    ├── openrouter_client.py
    ├── auth.py                # Argon2, HMAC e criptografia
    ├── database.py            # usuários e credenciais SQLite
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
docker run --rm -p 8000:8000 --env-file .env -v routemind-data:/app/data routemind
```

Depois de iniciar, abra `http://localhost:8000/register`, crie a conta, cadastre sua chave OpenRouter e gere uma chave RouteMind. Para o volume Docker acima, configure `ROUTEMIND_DATABASE_PATH=/app/data/routemind.db`.

### Endpoints

| Método | Endpoint | Autenticação | Finalidade |
|---|---|---|---|
| `GET` | `/register` | pública | formulário de cadastro |
| `POST` | `/register` | CSRF | criação da conta |
| `GET/POST` | `/login` | pública/CSRF | início de sessão |
| `GET` | `/dashboard` | sessão | credenciais e chaves do usuário |
| `POST` | `/openrouter-key` | sessão + CSRF | cadastrar ou substituir a chave OpenRouter |
| `POST` | `/keys` | sessão + CSRF | gerar uma chave RouteMind |
| `POST` | `/keys/{id}/revoke` | sessão + CSRF | revogar uma chave RouteMind |
| `POST` | `/logout` | sessão + CSRF | encerrar a sessão |
| `POST` | `/api/v1/chat/completions` | Bearer `rm_live_...` | proxy inteligente da OpenRouter |
| `GET` | `/health` | pública | verificação de saúde |

## Configuração

| Variável | Padrão | Finalidade |
|---|---:|---|
| `ROUTEMIND_SECRET_KEY` | inseguro para desenvolvimento | assina sessões, HMAC das API keys e deriva a chave de criptografia |
| `ROUTEMIND_DATABASE_PATH` | `routemind.db` | banco SQLite persistente |
| `ROUTEMIND_ENVIRONMENT` | `development` | use `production` em produção |
| `ROUTEMIND_SECURE_COOKIES` | `false` | exige cookie HTTPS; obrigatório em produção |
| `ROUTEMIND_OPENROUTER_BASE_URL` | URL oficial | upstream |
| `ROUTEMIND_CATALOG_TTL_SECONDS` | `900` | TTL do catálogo |
| `ROUTEMIND_CATALOG_MAX_STALE_SECONDS` | `3600` | stale máximo em falha |
| `ROUTEMIND_REQUEST_TIMEOUT_SECONDS` | `120` | timeout HTTP |
| `ROUTEMIND_DEFAULT_OUTPUT_TOKENS` | `1024` | reserva sem limite explícito |
| `ROUTEMIND_RATE_LIMIT_PER_MINUTE` | `60` | limite por chave/IP/processo |
| `ROUTEMIND_MAX_FALLBACK_ATTEMPTS` | `2` | tentativas totais |
| `ROUTEMIND_APP_URL` | vazio | `HTTP-Referer` opcional |
| `ROUTEMIND_APP_NAME` | `RouteMind` | `X-OpenRouter-Title` |

Em produção, gere `ROUTEMIND_SECRET_KEY` com pelo menos 32 caracteres aleatórios, mantenha-a em um secret manager e não a rotacione sem um plano de migração: os HMACs e credenciais criptografadas existentes dependem dela. O processo recusa inicialização em modo `production` se o segredo for inseguro ou cookies HTTPS estiverem desativados.

## Exemplos

Gratuito por padrão, usando a chave gerada no painel:

```bash
curl http://localhost:8000/api/v1/chat/completions \
  -H 'Authorization: Bearer rm_live_SUA_CHAVE_ROUTEMIND' \
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

client = OpenAI(
    base_url="http://localhost:8000/api/v1",
    api_key="rm_live_SUA_CHAVE_ROUTEMIND",
)
response = client.chat.completions.create(
    messages=[{"role": "user", "content": "Olá"}], stream=True
)
```

## Testes

```bash
.venv/bin/pytest -q
```

Os testes usam mocks. Uma validação real pode usar uma chave e modelo gratuito, mas deve ser opt-in porque catálogo, disponibilidade e rate limits mudam.

A suíte cobre cadastro, login, CSRF, criptografia, emissão e revogação de chaves, isolamento entre usuários, ausência de chave OpenRouter, seleção de modelos, custos, fallback e streaming SSE.

## Limitações conhecidas

- A classificação combina conteúdo, estrutura, modalidades e recursos, mas é heurística, não um classificador semântico treinado. Use `task_type` explícito quando crítico.
- O catálogo comprova compatibilidade técnica, não qualidade objetiva. Afinidade pela descrição é apenas um sinal; benchmarks versionados são a evolução recomendada.
- Rate limit, cache e tracking são locais; implantação distribuída requer Redis/persistência.
- SQLite é adequado para uma instância pequena; alta concorrência requer PostgreSQL e migrações versionadas.
- O custo efetivo do SSE aparece dentro do stream e ainda não é extraído pelo tracker.
- Não há recuperação de senha, verificação de e-mail, MFA, orçamento acumulado, conversão cambial, cobrança ou painel administrativo.
- Somente Chat Completions e `/health` são implementados.
- Campos desconhecidos são preservados, mas só o upstream confirma suporte por modelo/provedor.

## Segurança operacional

Senhas usam Argon2id. Sessões são assinadas, `HttpOnly`, `SameSite=Strict` e, em produção, `Secure`. Formulários mutáveis exigem token CSRF; respostas recebem CSP, bloqueio de frames, `nosniff` e política de referrer. O gateway não registra prompts nem segredos. A implantação ainda deve fornecer TLS, backup criptografado, rotação planejada, secret manager, observabilidade com redação, limites distribuídos e política de retenção.

### Cuidados com `ROUTEMIND_SECRET_KEY`

Esse segredo possui três funções derivadas e separadas: assinatura das sessões, HMAC das chaves RouteMind e criptografia das credenciais OpenRouter. Não faça rotação direta em uma instalação com dados existentes. Sem um procedimento de migração, a troca invalida todas as chaves RouteMind e torna as credenciais OpenRouter armazenadas indecifráveis.

O banco `routemind.db` e seus arquivos WAL devem ser persistidos e incluídos em backups protegidos. Mesmo com a criptografia das credenciais, o banco contém e-mails, hashes de senha e metadados de uso.
