# Zenless — By Fentalware

Zenless é um aplicativo Windows local para coordenar Roblox Studio, ChatGPT, DeepSeek e Hunyuan3D sem chaves de API. Ele usa sessões normais dos provedores em navegador gerenciado; login, MFA, CAPTCHA e consentimentos continuam manuais.

```text
pedido
  → leitura do Studio
  → proposta do ChatGPT
  → revisão independente do DeepSeek
  → aprovação do usuário
  → mutação verificada no Studio
  → QA e reparo limitado
  → revisão final real do DeepSeek
  → concluído ou bloqueado
```

## Como usar

1. Abra o Roblox Studio atualizado, deixe o projeto em **Edit** e conecte o servidor StudioMCP compatível.
2. Execute `Zenless.exe`.
3. Faça login em ChatGPT, DeepSeek e, quando necessário, Hunyuan. As sessões ficam no perfil local do Zenless; credenciais e cookies não passam pela interface React.
4. Envie um objetivo completo no Chat. O aplicativo mostra estados reais e solicita aprovação antes de cada bloco de escrita relevante.

Os dados persistentes ficam em `%LOCALAPPDATA%\Zenless`: SQLite, logs rotativos, perfis de navegador, anexos validados, snapshots, evidências e ativos gerados.

## Garantias principais

- Bridge HTTP/WebSocket somente em `127.0.0.1`, porta efêmera, token aleatório por processo, validação exata de host/origin e IDs de requisição.
- Core autoritativo: a UI solicita ações, mas não aplica alterações nem decide sucesso.
- Mutações com leitura atual, snapshot, precondição SHA-256, operação idempotente, aplicação, releitura e verificação. Divergência de precondição bloqueia a escrita.
- Recuperação conservadora: uma queda durante escrita/QA/revisão final não repete a operação automaticamente.
- ChatGPT como construtor e DeepSeek como revisor independente, inclusive depois de mutação e QA.
- Deltas reais dos navegadores são encaminhados pelo WebSocket; a resposta parcial não vira estado durável.
- Visual First versionado com seis PNGs canônicos (`FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`), QA visual e regeneração controlada.
- Hunyuan usa descoberta de capacidade e separa geometria de textura. Recursos não expostos pela UI do provedor são marcados como indisponíveis; não há progresso ou ativo fabricado.
- QA Breaker registra perfil, seed, casos, evidências, Output e resultado. Capacidades Roblox ausentes são `SKIPPED`/bloqueadas, nunca simuladas como sucesso.
- Encerramento cooperativo de Bridge, navegadores, StudioMCP, filas e banco.

## Limites reais

- A automação dos provedores depende da interface web atual de cada serviço e pode exigir atualização de seletores.
- O fallback Playwright é interno e provisionado sob demanda. Uma extensão de navegador não faz parte da rota normal.
- Importação de GLB local continua sujeita às capacidades expostas pelo StudioMCP/Roblox Studio.
- Multiplayer, VirtualInput e emulação de dispositivo só podem ser executados quando a conexão StudioMCP expõe a capacidade correspondente.
- O executável é um pacote `one-file`; este repositório não gera instalador MSI/Setup separado.

## Desenvolvimento

```powershell
python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
python -m ruff check .
python -m pyright
python -m pytest -o addopts= -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

`tests/live_studio_smoke.py` só inicia Play Test quando o Studio confirma **Edit** e sempre solicita **Stop** em `finally`. Ele requer uma instância real conectada; não é substituído por mock.

Para gerar a release:

```powershell
.\build.ps1
```

O script executa, nesta ordem, Ruff, Pyright, pytest, `npm ci`, ESLint, TypeScript, Vitest, Vite com Mock Mode desativado e, somente se tudo passar, PyInstaller. A saída única é `dist\Zenless.exe`.

## Árvore canônica

- `frontend/`: única fonte React/TypeScript/Vite e contrato de transporte.
- `zenless/core.py`: estado autoritativo e adaptadores expostos à UI.
- `zenless/web_bridge.py`: REST, WebSocket e arquivos autorizados locais.
- `zenless/orchestrator.py`: pipeline, gates, mutação e revisão final.
- `zenless/agent_gateway.py`: seleção WebView2 → Playwright por capacidade.
- `zenless/studio_mcp.py`: cliente StudioMCP.
- `zenless/store.py`: SQLite, operações idempotentes e recuperação.
- `zenless/qa_breaker.py`: planejamento, execução e evidência de QA.
- `Zenless.spec`: pacote Windows `one-file` sem console.

Detalhes: [ARCHITECTURE.md](ARCHITECTURE.md), [QA_ARCHITECTURE.md](QA_ARCHITECTURE.md), [frontend/BACKEND_CONTRACT.md](frontend/BACKEND_CONTRACT.md) e [RELEASE_NOTES.md](RELEASE_NOTES.md).

Licença GPL-3.0. Consulte `NOTICE.md`.
