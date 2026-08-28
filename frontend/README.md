# Zenless Web

Fonte canônica da interface React/TypeScript/Vite do Zenless. Produção serve `dist/` pelo Bridge Python local; `bridge/` e Mock Mode são fixtures de desenvolvimento, não o backend do executável.

## Desenvolvimento

```bash
npm ci
npm run dev
```

`.env.development` ativa o Mock Mode para trabalho isolado de UI. Para testar a interface contra o Core/Bridge Python real, use `VITE_ZENLESS_MOCK=false` e inicie o aplicativo/backend local.

## Gates

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

O gate oficial completo fica em `../build.ps1`; ele força Mock Mode desligado antes do build de produção e só empacota o EXE depois dos gates Python e frontend.

## Limites

- A UI apenas solicita ações e renderiza estado/eventos; Core/Orchestrator são autoritativos.
- Não adicione uma segunda árvore `src/` na raiz do repositório.
- Não edite `dist/` manualmente.
- Nunca exponha credenciais, cookies ou caminhos Windows arbitrários ao frontend.

Consulte `FRONTEND_ARCHITECTURE.md`, `BACKEND_CONTRACT.md` e `CODEX_HANDOFF.md`.
