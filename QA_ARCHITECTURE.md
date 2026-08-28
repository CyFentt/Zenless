# Arquitetura de QA

## Regra de evidência

Zenless separa quatro resultados:

- `PASSED`: o caso foi executado e a condição observada passou;
- `FAILED`: foi executado e houve divergência/erro;
- `SKIPPED`: a capacidade não estava disponível ou o caso não se aplicava;
- `NOT RUN`: nenhuma execução foi tentada nesta verificação.

Inspeção de código não transforma Play Test, provedor real, ativo visual ou máquina limpa em `PASSED`.

## Gate de release local

`build.ps1` interrompe no primeiro erro e só chama PyInstaller depois de:

1. `python -m ruff check .`;
2. `python -m pyright`;
3. `python -m pytest -o addopts= -q`;
4. `npm ci` em `frontend/`;
5. `npm run lint`;
6. `npm run typecheck`;
7. `npm run test`;
8. `npm run build` com `VITE_ZENLESS_MOCK=false`.

Esse gate cobre estilo/erros estáticos, tipos, lógica pura, Bridge local, persistência, protocolo, frontend e criação da SPA. Ele não prova serviços externos.

## QA Breaker no Studio

O QA Breaker seleciona perfil com base no risco, objetivo e ferramentas mutantes:

| Perfil | Uso | Limite esperado |
|---|---|---|
| `SMOKE` | alteração visual/local de baixo risco | poucos cenários e Play curto |
| `STANDARD` | mudança comum | evidência, Edit, Play/Output e smoke VirtualInput |
| `DEEP` | DataStore, remotes, física, multiplayer ou alto risco | casos anteriores + dispositivo + harness multiplayer opt-in |

Cada execução recebe `run_id` e seed derivada do job/run, persiste plano, casos, duração, contagens `passedCases`/`skippedCases`/`failedCases`, Output e falhas reproduzíveis. Cancelamento e tempo máximo são limites reais. O bloco `finally` solicita Stop quando Play foi iniciado.

Casos automáticos verificam:

- integridade da evidência de mutação e read-back;
- estado Edit antes do teste;
- Start Play, coleta de Output, busca de erro e Stop;
- transição inócua `Unknown` down/up por VirtualInput em `STANDARD`/`DEEP`, sem alegar comportamento de gameplay;
- aplicação, read-back, captura e restauração de viewport 390×844 Portrait no perfil `DEEP`;
- execução `StudioTestService` no perfil `DEEP` somente quando o projeto contém o marcador exato `ZENLESS_QA_MULTIPLAYER_V1`;
- revisão independente dos resultados quando DeepSeek está disponível.

Um cenário textual não é considerado executado apenas por aparecer no plano; cada item precisa de executor e resultado persistido próprios para contar como `PASSED`.

## Matriz de capacidade Roblox

| Área | Execução automática | Regra quando ausente |
|---|---|---|
| Edit/Play/Stop/Output | StudioMCP `get_studio_state`, `start_stop_play`, `get_console_output` | falha ou skip explícito conforme criticidade |
| TestEZ/Jest Roblox | runner/harness detectado no projeto ou Studio | `SKIPPED`; nunca inferir pelos arquivos |
| Multiplayer | `script_grep` + `execute_luau` Edit + marcador opt-in; 1–8 clientes no runner | `SKIPPED` sem o marcador/schema; nunca lançar por heurística |
| VirtualInput | `start_stop_play` + `execute_luau` Client com schema validado | `SKIPPED` sem capacidade; não simular clique por estado interno |
| Device emulator | `execute_luau` Edit + `screen_capture`; estado original validado/restaurado | `SKIPPED` sem capacidade; falha se captura/read-back/restore falhar |
| DataStore | ambiente de teste isolado, sem dados de produção | bloquear caso inseguro |

O harness multiplayer é propriedade do jogo e precisa declarar o protocolo opt-in; Zenless limita jogadores/tempo, exige retorno assinado e solicita cleanup. O smoke atual valida o transporte do harness, não substitui asserções específicas do gameplay no script do projeto. Testes de DataStore precisam de namespace exclusivo, cleanup idempotente e nunca devem tocar chaves de produção.

## QA de Visual First

Cada versão deve produzir seis arquivos PNG distintos. A verificação determinística registra:

- assinatura PNG e arquivo não vazio;
- dimensões mínimas;
- SHA-256 por vista e detecção de duplicata;
- direção/versionamento coerentes no metadata;
- rota de asset autorizada e renderização pela UI.

A verificação semântica compara identidade, proporções, cores, detalhes e orientação contra o master spec. Reprovação regenera apenas vistas indicadas ou todas em nova versão; nunca sobrescreve evidência aprovada.

## QA de Hunyuan/3D

Antes de enviar imagens, o adapter registra as capacidades observadas e o limite de uploads. A evidência separa:

1. vistas aprovadas realmente enviadas;
2. geometria concluída e GLB estruturalmente carregável;
3. textura/PBR aplicada à geometria aprovada;
4. download autorizado e visualização local;
5. regeneração de geometria ou textura como operações independentes.

Ausência de controle, limite incompatível, download sem arquivo ou GLB inválido falha a etapa. URL ou texto do provedor não é um modelo validado.

## E2E externo e máquina limpa

O checklist final exige observação manual/real de:

- abertura do EXE sem Python/Node/npm no PATH;
- WebView2 presente e caminho de provisionamento quando ausente;
- login normal e persistência de sessão de cada provedor;
- streaming ChatGPT e duas revisões DeepSeek;
- Six View, QA/regeneração e Hunyuan geometria/textura;
- Studio conectado, aprovação, precondição, aplicação, read-back, Play/Stop e Output;
- encerramento durante fase segura e durante fase mutante, verificando recuperação sem replay.

## Estado desta auditoria (2026-08-28)

| Verificação externa | Estado | Evidência |
|---|---|---|
| Roblox Studio conectado / Play Solo | `NOT RUN` | nenhuma instância StudioMCP estava conectada |
| Multiplayer / VirtualInput / device emulator | `NOT RUN` | dependem de Studio/harness real |
| Provedores reais e visual/3D E2E | `NOT RUN` | nenhuma sessão real foi usada nesta auditoria |
| Windows limpo | `NOT RUN` | não houve segunda máquina/VM limpa |

Os totais atuais dos gates locais e o hash do EXE devem ser registrados no relatório de entrega depois do build final, não antecipados neste documento.
