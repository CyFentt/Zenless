# Arquitetura do Zenless

## Visão geral

```text
React/Vite no WebView2
        │ REST + WebSocket autenticados
        ▼
LocalWebBridge (127.0.0.1, porta efêmera)
        │
        ▼
ZenlessCore ── EventBus ── SQLiteStore / StorageManager / ErrorBus
        │
        ├── ZenlessOrchestrator
        │      ├── AgentGateway ── WebView2 → Playwright interno
        │      │                       ├── ChatGPT
        │      │                       ├── DeepSeek
        │      │                       └── Hunyuan3D
        │      └── StudioMCPClient ── Roblox Studio
        │
        └── QABreaker ── StudioMCP + evidências + provedores
```

A interface é uma projeção de estado. Ela não decide que um provedor está pronto, não cria sucesso de QA e não escreve no Studio.

## Inicialização e encerramento

O executável resolve dois diretórios:

- recursos imutáveis: raiz do checkout em desenvolvimento ou `_MEIPASS` no PyInstaller;
- dados mutáveis: `%LOCALAPPDATA%\Zenless` ou `ZENLESS_DATA_ROOT` em testes controlados.

Os estágios públicos de boot (`CORE`, `STATE`, `BRIDGE`, `UI`, `BROWSER`, `AI`, `STUDIO`) refletem eventos reais de inicialização. Não há porcentagem sintética. O Bridge inicia antes de servir a SPA; serviços externos podem continuar `CONNECTING`, `OFF` ou `DEGRADED` sem congelar a UI.

No encerramento, o Core sinaliza cancelamento, interrompe QA, fecha as rotas de navegador, aguarda o Orchestrator por tempo limitado, fecha StudioMCP, faz manutenção do SQLite e encerra Bridge/Event Bus. Exceções não tratadas chegam ao ErrorBus e aos logs rotativos.

## Fronteira HTTP/WebSocket

`LocalWebBridge` aceita apenas `127.0.0.1`, valida host e origin exatos, usa porta escolhida pelo sistema e cria token aleatório por processo. REST autenticado usa `X-Zenless-Token`; WebSocket usa o mesmo token na abertura. Todo request recebe `X-Request-Id` validado ou gerado.

JSON, multipart e arquivos têm limites explícitos. Anexos passam por nome sanitizado e armazenamento controlado. Ativos são enviados por ID; a resolução final precisa permanecer dentro da raiz de dados autorizada.

O WebSocket transporta eventos do Core. Deltas de provedor são provisórios e servem apenas à exibição; a resposta completa é persistida depois do término.

## Pipeline do Orchestrator

```text
COLLECTING_CONTEXT → CREATING → REVIEWING/REVISING
        → visual/3D gates opcionais
        → WAITING_CHANGE_APPROVAL
        → APPLYING → TESTING/FIXING
        → FINAL_REVIEW → COMPLETE | BLOCKED | FAILED
```

ChatGPT coleta contexto adicional e produz ações estruturadas. A política separa leitura de mutação e bloqueia ferramentas desconhecidas ou críticas. DeepSeek revisa a proposta de forma independente; `REVISE` volta ao construtor com limite de rodadas e `BLOCK` interrompe o fluxo.

Depois de mutação e QA, o Orchestrator coleta estado/evidência atualizados e chama DeepSeek novamente. A revisão final é uma chamada real, persistida separadamente da revisão inicial. Uma revisão final pode aprovar, pedir reparo limitado com nova aplicação/QA ou bloquear.

## Segurança da mutação

Cada mutação aprovada carrega `job_id`, `request_id`, `operation_id` e `mutation_id` correlacionáveis. Para edição de script, a sequência é:

1. ler fonte atual e calcular SHA-256;
2. criar snapshot durável;
3. vincular o hash esperado à ação aprovada;
4. reivindicar uma chave de idempotência no SQLite;
5. reler imediatamente e comparar a precondição;
6. aplicar via StudioMCP;
7. reler e verificar conteúdo/hash esperado;
8. concluir a operação com evidência ou marcá-la como falha.

Uma precondição divergente significa que o Studio mudou desde a aprovação; a escrita é bloqueada. Uma operação já concluída pode devolver a evidência registrada, mas uma operação `pending` deixada por queda não é repetida.

## Persistência e recuperação

SQLite usa foreign keys, busy timeout e WAL. Tarefas, mensagens, eventos, aprovações, operações, contexto, ativos, execuções e casos de teste são persistidos. Arquivos grandes ficam no StorageManager e o banco guarda metadados/caminhos internos.

Na abertura, tarefas interrompidas antes da zona de escrita podem ser pausadas. Estágios potencialmente mutantes (`APPLYING`, `TESTING`, `FIXING`, `FINAL_REVIEW`) viram `BLOCKED`; o usuário deve inspecionar o Studio e as evidências antes de uma nova tarefa. Recuperação nunca reexecuta escrita por inferência.

## Provedores e streaming

O AgentGateway tenta WebView2 embutido primeiro. Se a capacidade necessária não estiver presente, pode usar o Playwright interno e persistente. Login normal pode abrir a página do provedor. Uma extensão externa não é requisito e não participa da release padrão.

Seletores, modelos e capacidades são descobertos da sessão viva. Durante uma resposta, cada crescimento confirmado do texto gera um delta; cancelamento, timeout e fechamento são propagados. A UI dos provedores é uma dependência mutável, portanto falhas de descoberta devem ser diagnósticos e não estados `READY` falsos.

## Visual First e 3D

O master spec visual gera seis prompts presos à mesma identidade. Cada direção resulta em um PNG real e separado sob `assets/<job>/concept/vN/`, com hash, dimensões, versão e direção. QA determinístico valida arquivo/PNG/dimensões/duplicatas; QA semântico compara consistência. Regenerar tudo ou uma vista cria nova versão e preserva evidência anterior.

Somente vistas aprovadas alimentam Hunyuan. O adapter descobre upload, quantidade máxima de imagens, geração de geometria, geração de textura e download. A etapa de geometria produz/valida um GLB; a etapa de textura/PBR usa a geometria aprovada e produz a versão final. Se a conta/UI não expuser uma etapa, o job registra `CAPABILITY_UNAVAILABLE`.

## Empacotamento

`Zenless.spec` gera um executável Windows `one-file`, sem console, contendo `frontend/dist`, assets, vendor e metadados de licença. O build de produção desativa Mock Mode e exclui toolkits GUI não usados, inclusive Tkinter. Node/npm/Python não são necessários para executar o artefato final.
