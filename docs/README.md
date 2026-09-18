# Documentação do RouteMind

Esta pasta documenta exclusivamente o comportamento do RouteMind: autenticação, seleção de modelos, controle de custos, fallback, formato local de erros e uso do endpoint disponibilizado pelo projeto.

## Conteúdo

- [API de Chat Completions do RouteMind](chat-completions.md)
- [Exemplos de uso do RouteMind](examples.md)

## Escopo de compatibilidade

O RouteMind implementa `POST /api/v1/chat/completions`. O objeto `routemind` controla a política local e é removido antes da chamada upstream.

Campos compatíveis de Chat Completions são preservados, mas a documentação desta pasta não tenta reproduzir o contrato do upstream. Ela descreve apenas como esses campos afetam o RouteMind e o que a aplicação garante.
