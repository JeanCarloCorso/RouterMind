# Exemplos de uso do RouteMind

Todos os exemplos chamam o RouteMind. Substitua `https://seu-dominio.example` pela URL da instalação e `rm_live_SUA_CHAVE` pela chave gerada no dashboard.

## Chamada gratuita com seleção automática

```bash
curl https://seu-dominio.example/api/v1/chat/completions \
  -H 'Authorization: Bearer rm_live_SUA_CHAVE' \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Explique APIs REST em três frases."}]}'
```

Como `routemind` foi omitido, o gateway aplica:

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

## Todos os parâmetros próprios do RouteMind

```bash
curl https://seu-dominio.example/api/v1/chat/completions \
  -H 'Authorization: Bearer rm_live_SUA_CHAVE' \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {"role": "system", "content": "Seja objetivo."},
      {"role": "user", "content": "Revise esta função Python."}
    ],
    "max_completion_tokens": 800,
    "temperature": 0.2,
    "routemind": {
      "free_only": false,
      "max_cost": 0.02,
      "currency": "USD",
      "task_type": "coding",
      "preferred_models": ["provider/model-preferido"],
      "excluded_models": ["provider/model-bloqueado"],
      "fallback_enabled": true
    }
  }'
```

O RouteMind procura um modelo compatível e rejeita a chamada antes do upstream se a estimativa ultrapassar US$ 0,02.

## Modelo explícito

```json
{
  "model": "provider/model:free",
  "messages": [{"role": "user", "content": "Escreva um haicai."}],
  "max_completion_tokens": 100,
  "routemind": {
    "free_only": true,
    "max_cost": 0,
    "fallback_enabled": false
  }
}
```

O slug é ilustrativo. Se o modelo não estiver no catálogo atual, não for gratuito ou não tiver capacidade suficiente, o RouteMind responde `422` em vez de escolher outro.

## Preferência e exclusão de modelos

```json
{
  "messages": [{"role": "user", "content": "Resuma este documento."}],
  "routemind": {
    "preferred_models": ["provider/model-a:free", "provider/model-b:free"],
    "excluded_models": ["provider/model-c:free"]
  }
}
```

Preferência altera a ordenação, mas não obriga o uso de um modelo incompatível. Exclusão é uma proibição.

## Tools

```json
{
  "messages": [{"role": "user", "content": "Qual é o clima em Curitiba?"}],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "consultar_clima",
        "description": "Consulta o clima atual",
        "parameters": {
          "type": "object",
          "properties": {"cidade": {"type": "string"}},
          "required": ["cidade"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "routemind": {"free_only": true, "task_type": "auto"}
}
```

O RouteMind usa `tools` para eliminar modelos incompatíveis. Se o modelo solicitar a função, a aplicação cliente deve executá-la e enviar o resultado em uma nova requisição.

## Resposta estruturada

```json
{
  "messages": [{"role": "user", "content": "Retorne um título e duas palavras-chave."}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "resumo",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "titulo": {"type": "string"},
          "palavras_chave": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["titulo", "palavras_chave"],
        "additionalProperties": false
      }
    }
  }
}
```

O RouteMind seleciona somente modelos que declaram suporte a `response_format`.

## Streaming

```bash
curl --no-buffer https://seu-dominio.example/api/v1/chat/completions \
  -H 'Authorization: Bearer rm_live_SUA_CHAVE' \
  -H 'Content-Type: application/json' \
  -d '{"stream":true,"messages":[{"role":"user","content":"Conte uma história curta."}]}'
```

Resposta abreviada:

```text
data: {"id":"gen-stream-123","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Era"}}]}

data: {"id":"gen-stream-123","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":" uma vez"}}]}

data: [DONE]
```

O RouteMind não reconstrói os chunks e não faz fallback depois que o primeiro byte do stream foi enviado.

## Exemplo de resposta de sucesso

Este é um exemplo do corpo que o RouteMind pode retransmitir:

```json
{
  "id": "gen-1789731377-example",
  "object": "chat.completion",
  "created": 1789731377,
  "model": "provider/model:free",
  "provider": "ProviderName",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "Uma API REST organiza a comunicação em torno de recursos."
      }
    }
  ],
  "usage": {
    "prompt_tokens": 29,
    "completion_tokens": 18,
    "total_tokens": 47,
    "cost": 0
  }
}
```

O RouteMind não garante a presença de campos opcionais do upstream. O modelo efetivamente usado aparece em `model`; quando o upstream fornece custo real, ele aparece dentro de `usage`.

## Erros do RouteMind

Chave RouteMind inválida — HTTP 401:

```json
{"error":{"message":"Invalid RouteMind API key","code":"invalid_api_key"}}
```

Conta sem chave OpenRouter — HTTP 403:

```json
{"error":{"message":"No valid OpenRouter key is configured for this account","code":"openrouter_key_missing"}}
```

Corpo inválido — HTTP 400:

```json
{"error":{"message":"messages is required and must be a non-empty array","code":"invalid_request"}}
```

Nenhum modelo elegível — HTTP 422:

```json
{
  "error": {
    "message": "No model satisfies capabilities and the per-request cost limit",
    "code": "no_eligible_model",
    "metadata": {"free_only": true, "max_cost_usd": 0}
  }
}
```

## Python com cliente OpenAI

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://seu-dominio.example/api/v1",
    api_key="rm_live_SUA_CHAVE",
)

completion = client.chat.completions.create(
    messages=[{"role": "user", "content": "Olá!"}],
    temperature=0.2,
)

print(completion.choices[0].message.content)
```

Para enviar o objeto exclusivo `routemind`, use o mecanismo de corpo extra disponível na versão do SDK ou uma requisição HTTP direta.
