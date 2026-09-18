# API de Chat Completions do RouteMind

Esta página documenta o comportamento do **RouteMind**. Ela não substitui nem reproduz a documentação da OpenRouter.

## Endpoint

```http
POST /api/v1/chat/completions
Authorization: Bearer rm_live_SUA_CHAVE_ROUTEMIND
Content-Type: application/json
```

O cliente envia uma chave RouteMind. A aplicação identifica o proprietário, recupera a chave OpenRouter criptografada dessa conta e faz a chamada upstream sem expor essa credencial.

## Cabeçalhos aceitos pelo RouteMind

| Cabeçalho | Obrigatório | Finalidade |
|---|---:|---|
| `Authorization` | **Sim** | `Bearer` seguido da chave `rm_live_...` gerada no dashboard. |
| `Content-Type` | **Sim** | Corpo JSON; use `application/json`. |

Outros cabeçalhos do cliente não fazem parte do contrato de encaminhamento do RouteMind. O gateway monta seus próprios cabeçalhos para o upstream.

## Corpo da requisição

### Campos interpretados pelo RouteMind

| Campo | Tipo | Obrigatório | Padrão | Comportamento no RouteMind |
|---|---|---:|---|---|
| `messages` | array | **Sim** | — | Deve ser um array não vazio. Cada item deve ser um objeto com `role` string e a propriedade `content`. O conteúdo é usado para estimar tokens, contexto e tipo da tarefa. |
| `model` | string | Não | seleção automática | Restringe a seleção ao modelo indicado. O RouteMind não substitui silenciosamente um modelo explícito. |
| `stream` | boolean | Não | `false` | Quando `true`, devolve os eventos SSE recebidos do upstream e encerra com `[DONE]`. Não há retry depois que o stream começa. |
| `max_completion_tokens` | inteiro | Não | configuração do servidor | Define a reserva estimada de saída usada no cálculo de custo e contexto. |
| `max_tokens` | inteiro | Não | configuração do servidor | Alternativa legada para o limite de saída. O RouteMind prioriza `max_completion_tokens` quando ambos aparecem. |
| `tools` | array | Não | — | Faz o roteador exigir um modelo compatível com ferramentas. As ferramentas são executadas pela aplicação cliente, não pelo RouteMind. |
| `tool_choice` | string ou objeto | Não | — | Também faz parte da verificação de compatibilidade com ferramentas. |
| `response_format` | objeto | Não | — | Faz o roteador exigir suporte a resposta estruturada. O schema enviado é repassado sem alteração. |
| `reasoning` | objeto | Não | — | Indica necessidade de recurso de reasoning durante a seleção. |
| `reasoning_effort` | string | Não | — | Também sinaliza uma requisição de reasoning. |
| `modalities` | array | Não | `text` | Modalidades de saída exigidas. O roteador elimina modelos incompatíveis. |
| `plugins` | array | Não | — | Uma lista não vazia é recusada atualmente porque plugins podem gerar custos não representados pelo preço-base do modelo. |
| `routemind` | objeto | Não | veja abaixo | Política local de roteamento e custo. É removido antes da chamada ao upstream. |

### Campos compatíveis encaminhados sem interpretação local

Campos de Chat Completions que não pertencem ao objeto `routemind` são preservados no payload sempre que o RouteMind consegue fazer o preflight com segurança. Exemplos incluem:

- `temperature`, `top_p`, `top_k`, `top_a` e `min_p`;
- `frequency_penalty`, `presence_penalty` e `repetition_penalty`;
- `stop`, `seed`, `logit_bias`, `logprobs` e `top_logprobs`;
- `parallel_tool_calls` e opções das ferramentas;
- `provider`, `service_tier`, `session_id`, `metadata`, `trace` e `user`;
- configurações específicas de modalidade, cache, streaming ou depuração.

O RouteMind não redefine a semântica desses campos. A aceitação final depende do modelo, do provedor e do upstream. Campos desconhecidos também são preservados quando tecnicamente seguro, mas não passam a ser uma funcionalidade implementada pelo RouteMind por causa disso.

## Objeto `routemind`

Estes são os parâmetros próprios do projeto:

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---:|---|---|
| `free_only` | boolean | Não | `true` | Permite somente modelos cujo custo relevante foi confirmado como zero no catálogo. |
| `max_cost` | número ≥ 0 | Não | `0` | Teto de custo **estimado por requisição**, em USD. Não representa saldo ou orçamento mensal. |
| `currency` | string | Não | `USD` | Apenas `USD` é aceito. |
| `task_type` | string | Não | `auto` | Categoria informada pelo cliente. Em `auto`, o RouteMind classifica a solicitação. |
| `preferred_models` | array de strings | Não | `[]` | Modelos priorizados entre os candidatos elegíveis. Não funciona como allowlist. |
| `excluded_models` | array de strings | Não | `[]` | Modelos que nunca podem ser selecionados. Não pode sobrepor `preferred_models`. |
| `fallback_enabled` | boolean | Não | `true` | Permite tentar outro candidato elegível nos erros pré-geração suportados. |

Regras de validação:

- `free_only=false` exige `max_cost > 0`;
- `currency` deve ser `USD`;
- o mesmo modelo não pode aparecer em `preferred_models` e `excluded_models`;
- campos desconhecidos dentro de `routemind` são recusados;
- `routemind` nunca é encaminhado ao upstream.

## Como o RouteMind seleciona um modelo

1. Autentica a chave RouteMind e carrega a chave OpenRouter da conta proprietária.
2. Valida `messages` e o objeto `routemind`.
3. Classifica a tarefa e identifica modalidades e recursos necessários.
4. Consulta o catálogo em cache da conta.
5. Filtra contexto, modalidades, ferramentas, resposta estruturada, reasoning, exclusões e modelo explícito.
6. Descarta preços ausentes ou inválidos.
7. Estima entrada e saída e aplica `free_only`/`max_cost`.
8. Ordena os candidatos e chama o primeiro modelo elegível.

O custo estimado considera tokens de entrada, reserva de saída, preço por requisição e componentes relevantes publicados no catálogo. A estimativa reduz risco, mas não é uma garantia contábil do custo final.

## Fallback

O fallback respeita as mesmas regras financeiras e de capacidade da seleção inicial. Ele ocorre somente quando habilitado e para respostas anteriores à geração com status `403`, `404`, `429`, `502` ou `503`.

- nunca troca um `model` explícito;
- nunca seleciona um modelo pago quando `free_only=true`;
- nunca tenta novamente depois que um stream começou;
- nunca repete uma resposta HTTP `200`;
- limita tentativas por `ROUTEMIND_MAX_FALLBACK_ATTEMPTS`.

## Respostas

Uma resposta bem-sucedida não é reconstruída pelo RouteMind. O status, corpo JSON e campos fornecidos pelo upstream são preservados. Por isso, normalmente aparecem `id`, `object`, `created`, `model`, `choices` e `usage`, mas campos adicionais também podem existir.

Em streaming, o RouteMind retransmite os bytes SSE sem reagrupar deltas.

## Métricas armazenadas

Para cada requisição autenticada, o RouteMind armazena o usuário, data UTC, resultado, status HTTP, modelo, tokens de entrada/saída/total e tempo de resposta. Tokens ficam vazios quando o upstream não fornece `usage`.

O histórico não armazena `messages`, prompts, respostas ou argumentos de ferramentas. O dashboard apresenta os totais e as 25 chamadas mais recentes da própria conta.

## Erros produzidos localmente

Erros internos usam este envelope:

```json
{
  "error": {
    "message": "Descrição do erro",
    "code": "codigo_estavel",
    "metadata": {}
  }
}
```

`metadata` aparece somente quando existem detalhes adicionais.

| Status | Código comum | Quando ocorre |
|---:|---|---|
| `400` | `invalid_request` | JSON inválido, `messages` ausente/inválido ou configuração `routemind` inválida. |
| `401` | `invalid_api_key` | Chave RouteMind ausente ou inválida. |
| `403` | `openrouter_key_missing` | A conta não possui uma chave OpenRouter válida cadastrada. |
| `422` | `no_eligible_model` | Nenhum modelo satisfaz capacidade, exclusões e teto por requisição. |
| `429` | `rate_limit_exceeded` | Limite local por chave/IP excedido. |
| `502` | `upstream_error` | Falha de rede ao acessar o upstream. |
| `503` | `catalog_unavailable` | Catálogo indisponível e cache antigo demais. |
| `504` | `upstream_timeout` | Timeout na chamada upstream. |

Respostas HTTP recebidas do upstream são repassadas sempre que possível e podem usar outro formato de erro.

Veja [exemplos de uso do RouteMind](examples.md).
