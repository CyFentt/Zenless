# Release Notes

## Unreleased — 2026-08-28

### Core e segurança

- Bridge Python real local-only com porta efêmera, token aleatório, host/origin exatos, request IDs, WebSocket autenticado, multipart limitado e assets servidos por ID.
- SQLite ampliado para contexto/ativos/testes/revisão final, operações idempotentes e recuperação conservadora de jobs interrompidos.
- Mutação protegida por snapshot, precondição SHA-256, claim de operação, read-back e evidência correlacionada. Operação pendente depois de crash não é repetida automaticamente.
- Corrigida a janela de corrida na abertura do WebSocket: a inscrição no Event Bus ocorre antes de concluir o handshake.
- ErrorBus e logs rotativos recebem falhas globais, do Bridge, navegador, Studio e pipeline.

### Agentes, visual e 3D

- Deltas observados em WebView2/Playwright chegam à UI como stream; somente respostas completas são persistidas.
- DeepSeek executa revisão independente antes da aprovação e revisão final real depois de mutação/QA, com `APPROVE`, reparo limitado ou `BLOCK`.
- Visual First gera seis PNGs separados e versionados com master spec, QA determinístico/semântico e regeneração de uma vista ou conjunto.
- Hunyuan descobre capacidade/limite de imagens e trata geometria e textura como etapas separadas; capacidade ausente vira erro explícito, sem progresso ou artefato fabricado.

### QA e recuperação

- QA Breaker registra perfil, seed, plano, casos, Output, falhas e revisão; Play sempre solicita Stop em cleanup.
- Adicionados smokes condicionais e limitados para VirtualInput, emulador com captura/restore e `StudioTestService` com marcador opt-in; ausência de ferramenta/schema/harness permanece `SKIPPED` em vez de sucesso simulado.
- TestEZ/Jest Roblox continua dependente de um runner explícito do projeto e não é inferido por inspeção de arquivos.
- Jobs interrompidos antes de escrita podem ser pausados; jobs interrompidos em estágios potencialmente mutantes são bloqueados para inspeção.

### Frontend e release

- `frontend/` agora é a única árvore React/TypeScript/Vite. A cópia raiz obsoleta (`src/`, `bridge/`, packages e configs) foi removida.
- Contrato/handoff/documentação atualizados para o backend real e seus limites verificáveis.
- `build.ps1` bloqueia PyInstaller até Ruff, Pyright, pytest, ESLint, TypeScript, Vitest e Vite passarem; dependências frontend são reinstaladas com `npm ci`.
- `Zenless.spec` mantém pacote Windows `one-file`, sem console, e exclui Tkinter/toolkits GUI não usados.

### Verificação

| Gate | Resultado atual |
|---|---|
| Ruff | `PASS` |
| Pyright | `PASS` — 0 errors, 0 warnings |
| pytest | `PASS` — 49 passed em 55.05 s |
| ESLint | `PASS` |
| TypeScript | `PASS` |
| Vitest | `PASS` — 3 arquivos, 45 testes |
| Vite produção (`VITE_ZENLESS_MOCK=false`) | `PASS` |
| PyInstaller one-file | `PASS` — `Zenless.exe`, SHA-256 `DD3C484009D7534666C033DFEF51A1A9DE803BEBCF0E838554B0D62E7438FC32` |
| Smoke do EXE congelado | `PASS` — `--no-provision --smoke-test`, splash nativa sem erro e nenhum processo Zenless restante |
| Studio/Play/Output real | `NOT RUN` — nenhum StudioMCP conectado nesta auditoria |
| Provedores/visual/Hunyuan E2E real | `NOT RUN` |
| Multiplayer/VirtualInput/device emulator | `NOT RUN` |
| Windows limpo | `NOT RUN` |

### Limites conhecidos

- Sites dos provedores e permissões de conta mudam sem versionamento pelo Zenless; seletores/capacidades podem exigir manutenção.
- A release gera `Zenless.exe`; não há MSI/Setup separado.
- GLB local ainda depende da importação/capacidade que Roblox Studio e StudioMCP efetivamente expuserem.
- O Vite reportou um chunk lazy grande do visualizador GLB e Browserslist desatualado; isso não bloqueou o bundle de produção. `npm ci` também reportou avisos transitivos que não foram atualizados automaticamente sem revisão de dependências.
