# Zenless — By Fentalware

Aplicativo Windows que coordena Roblox Studio, ChatGPT, DeepSeek e Hunyuan3D sem exigir chaves de API:

`pedido → contexto StudioMCP → criação → revisão → aprovação → aplicação → Play Test → reparo limitado → concluído`

## Uso

1. Abra o Roblox Studio atualizado e deixe o projeto em **Edit** com o servidor MCP do Studio habilitado.
2. Abra `Zenless.exe`. A tela inicial verifica banco, WebView2 e integrações; se o WebView2 estiver ausente, o redistribuível oficial incluído é validado e instalado silenciosamente.
3. Na primeira vez, use **Login** para ChatGPT, DeepSeek e, opcionalmente, Hunyuan. Login, CAPTCHA, MFA e consentimentos permanecem manuais. As sessões são persistidas em `%LOCALAPPDATA%\Zenless\webview-profile`.
4. Envie um único objetivo completo no Chat. O Zenless mostra o progresso e pede aprovação antes de alterações relevantes no Studio.

O fluxo normal não exige Python, Chrome, Playwright, WebView2 ou extensão instalados manualmente. O navegador WebView2 fica gerenciado pelo Zenless e só aparece quando a intervenção do usuário é necessária.

## Rotas web

1. **WebView2** embutido, com perfil persistente e uma página por provedor.
2. **Playwright** gerenciado, baixado automaticamente apenas se uma capacidade obrigatória falhar no WebView2.
3. Se as duas rotas falharem, a capacidade é marcada como indisponível; nenhuma extensão é exigida ou instalada.

O suporte nunca é simulado: cada provedor só fica `Ready` após teste real de sessão e DOM. Alterações de interface do site podem exigir atualização dos seletores.

## Recursos

- Estado e fila em SQLite, logs rotativos, diagnóstico central e snapshots.
- ChatGPT como criador e DeepSeek como revisor independente.
- Contexto total disponível pelo StudioMCP: árvore, scripts, estado, Output e Play Test.
- Gates de aprovação, validação de schema/política, releitura pós-edição e reparos limitados.
- Hunyuan3D opcional, download controlado de GLB e prévia 3D integrada/expandida.
- Ferramentas nativas de geração 3D do Roblox, quando disponíveis, também passam por aprovação.
- Encerramento cooperativo; tarefas web e Studio são serializadas para evitar rajadas de prompts.

## Limites de segurança

- O Zenless não solicita, lê nem exporta senhas ou cookies.
- CAPTCHA, MFA, consentimentos, publicação e compras nunca são contornados.
- O StudioMCP atual não importa diretamente um GLB local. Use o **3D Importer** para arquivos locais; ativos criados por ferramentas nativas entram pelo próprio Studio.

## Arquivos principais

- `frontend/`: HUD React congelada e visualizador 3D.
- `zenless/core.py`: estado autoritativo e adaptadores do frontend.
- `zenless/web_bridge.py`: REST/WebSocket local autenticado.
- `zenless/orchestrator.py`: pipeline, gates e reparos.
- `zenless/agent_gateway.py`: WebView2 → Playwright.
- `zenless/webview2_browser.py` e `zenless/webview_host.py`: navegador embutido.
- `zenless/studio_mcp.py`: cliente StudioMCP.
- `zenless/provisioning.py`: preparação automática do WebView2.
- `zenless/qa_breaker.py`: testes limitados, evidências e revisão.

## Desenvolvimento

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pyright
python -m pytest -o addopts= -q
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
python tests/live_studio_smoke.py
.\build.ps1
```

`live_studio_smoke.py` inicia Play Test somente quando o Studio confirma **Edit** e sempre solicita **Stop** em `finally`.

Licença: GPL-3.0. Consulte `NOTICE.md`.
