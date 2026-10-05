import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi, isMockMode, getMockApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tabs, Toggle, Select } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import { StatusDot, StatusBadge } from '@/components/StatusDot';
import { Modal } from '@/components/Modal';
import type { ConnectionInfo, Diagnostic, LocalAIState, ModelCatalog, ModelSettings, ProviderId, Settings } from '@/types';

type SettingsTab = 'general' | 'models' | 'links' | 'library' | 'logs';

export function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('general');
  const settings = useStore((s) => s.settings);
  const setSettings = useStore((s) => s.setSettings);
  const connections = useStore((s) => s.connections);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getApi().getSettings(), getApi().getModels()])
      .then(([nextSettings, nextCatalog]) => {
        if (!active) return;
        setSettings(nextSettings);
        setCatalog(nextCatalog);
      })
      .catch((error) => frontendDiagnostics.capture(error, 'settings', 'Failed to load settings'));
    return () => { active = false; };
  }, [setSettings]);

  return (
    <div className="flex flex-col h-full">
      <Tabs
        tabs={[
          { id: 'general', label: 'GENERAL' },
          { id: 'models', label: 'MODELS' },
          { id: 'links', label: 'LINKS' },
          { id: 'library', label: 'LIBRARY' },
          { id: 'logs', label: 'LOGS' },
        ]}
        active={tab}
        onChange={(t) => setTab(t as SettingsTab)}
      />
      <div className="flex-1 overflow-y-auto scrollbar-zen">
        {tab === 'general' && <GeneralTab settings={settings} onChange={setSettings} />}
        {tab === 'models' && <ModelsTab settings={settings} catalog={catalog} onChange={setSettings} />}
        {tab === 'links' && <LinksTab connections={connections} />}
        {tab === 'library' && <LibraryTab />}
        {tab === 'logs' && <LogsTab />}
      </div>
    </div>
  );
}

function GeneralTab({ settings, onChange }: { settings: Settings | null; onChange: (s: Settings) => void }) {
  const [projectDraft, setProjectDraft] = useState(settings?.projectRoot ?? '');
  const [indexState, setIndexState] = useState<'IDLE' | 'INDEXING' | 'READY' | 'ERROR'>('IDLE');

  useEffect(() => {
    setProjectDraft(settings?.projectRoot ?? '');
  }, [settings?.projectRoot]);

  if (!settings) return <EmptyState />;

  const persist = async (patch: Partial<Settings>) => {
    try {
      const next = await getApi().updateSettings(patch);
      onChange(next);
      return next;
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', 'Failed to update general settings');
      return null;
    }
  };

  const runIndex = async () => {
    setIndexState('INDEXING');
    try {
      await getApi().reindexProject(true);
      setIndexState('READY');
    } catch (error) {
      setIndexState('ERROR');
      frontendDiagnostics.capture(error, 'settings', 'Project indexing failed');
    }
  };

  return (
    <div className="p-6 max-w-2xl mx-auto w-full space-y-6 animate-fade-in">
      <Section title="BEHAVIOR">
        <Row label="Default Approval" hint="ASK requires confirmation. SAFE AUTO skips only reviewed low-risk write gates. FULL AUTO skips local approval gates without bypassing policy blocks.">
          <Select
            value={settings.approvalMode}
            options={[
              { id: 'ASK', label: 'ASK' },
              { id: 'SAFE_AUTO', label: 'SAFE AUTO' },
              { id: 'FULL_AUTO', label: 'FULL AUTO' },
            ]}
            onChange={(value) => void persist({ approvalMode: value as Settings['approvalMode'] })}
          />
        </Row>
        <Row label="Max Revisions" hint="Maximum revision attempts per job">
          <input
            type="number"
            value={settings.maxRevisions}
            min={1}
            max={64}
            onChange={(event) => void persist({ maxRevisions: Number.parseInt(event.target.value, 10) || 1 })}
            className="w-12 h-6 text-2xs text-center text-ink-50 bg-ink-800 border border-ink-600 focus:border-ink-500"
          />
        </Row>
      </Section>
      <Section title="PROJECT">
        <Row label="Optional local files" hint="The open Studio game is selected automatically. Choose a folder only for a separate Rojo or local files project.">
          <div className="flex items-center gap-2 w-full">
            <input
              value={projectDraft}
              onChange={(event) => setProjectDraft(event.target.value)}
              onBlur={() => {
                if (projectDraft.trim() !== settings.projectRoot) void persist({ projectRoot: projectDraft.trim() });
              }}
              spellCheck={false}
              placeholder="Project folder"
              className="w-full min-w-0 h-8 px-2 text-2xs font-mono text-ink-50 bg-ink-800 border border-ink-600 focus:border-zen-red"
            />
            <button
              onClick={() => {
                const picker = window.pywebview?.api?.select_project_folder;
                if (!picker) return;
                void picker(projectDraft).then(async (value) => {
                  const selected = value.trim();
                  if (!selected) return;
                  setProjectDraft(selected);
                  const saved = await persist({ projectRoot: selected });
                  if (saved) await runIndex();
                });
              }}
              className="h-6 px-2 text-2xs uppercase tracking-wider border border-ink-600 text-ink-100 hover:border-zen-red hover:text-ink-0 transition-colors"
            >
              BROWSE
            </button>
          </div>
        </Row>
        <Row label="Semantic Index" hint="Local semantic and keyword index powered by mcp-code-search">
          <Toggle checked={settings.semanticIndex} onChange={(value) => void persist({ semanticIndex: value })} />
        </Row>
        <Row label="Local AI" hint="Use the installed Qwen model for building, review, planning, and QA when web text providers are unavailable">
          <Toggle checked={settings.localAI} onChange={(value) => void persist({ localAI: value })} />
        </Row>
        <Row label="Index" hint="Incrementally index changed project files">
          <button
            disabled={!settings.projectRoot || indexState === 'INDEXING'}
            onClick={() => void runIndex()}
            className="h-6 px-2 text-2xs uppercase tracking-wider border border-ink-600 text-ink-100 hover:border-zen-red hover:text-ink-0 disabled:opacity-40 transition-colors"
          >
            {indexState === 'INDEXING' ? 'INDEXING' : indexState === 'READY' ? 'READY' : indexState === 'ERROR' ? 'RETRY' : 'INDEX'}
          </button>
        </Row>
      </Section>
      <Section title="CONNECTION">
        <Row label="Bridge Port" hint="Assigned automatically to an authenticated loopback bridge">
          <span className="text-2xs font-mono text-ink-200">{settings.bridgePort || 'EPHEMERAL'}</span>
        </Row>
      </Section>
      <Section title="MODE">
        <Row label="Mock Mode" hint="Use mock data instead of real bridge">
          <span className={`text-2xs uppercase tracking-wider ${isMockMode() ? 'text-zen-okBright' : 'text-ink-400'}`}>
            {isMockMode() ? 'ON' : 'OFF'}
          </span>
        </Row>
      </Section>
    </div>
  );
}

function ModelsTab({ settings, catalog, onChange }: { settings: Settings | null; catalog: ModelCatalog | null; onChange: (s: Settings) => void }) {
  if (!settings || !catalog) return <EmptyState />;
  const models = settings.models;

  const selectModel = async (provider: 'chatgpt' | 'deepseek' | 'gemini' | 'hunyuan', value: string) => {
    try {
      await getApi().setModel(provider, value);
      const nextModels: ModelSettings = provider === 'hunyuan'
        ? { ...models, hunyuan: { ...models.hunyuan, version: value } }
        : { ...models, [provider]: { ...models[provider], model: value } };
      onChange({ ...settings, models: nextModels });
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', `Failed to set ${provider} model`);
    }
  };

  const setRouting = async (enabled: boolean) => {
    try {
      await getApi().setSmartRouting(enabled);
      onChange({ ...settings, models: { ...models, smartRouting: enabled } });
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', 'Failed to update smart routing');
    }
  };

  const available = (items: { id: string; label: string; available?: boolean }[]) => items.filter((item) => item.available !== false);

  return (
    <div className="p-6 max-w-2xl mx-auto w-full space-y-6 animate-fade-in">
      <p className="text-xs text-ink-300 leading-relaxed">Model choices are loaded from connected providers. Reasoning and generation quality follow their available controls. Task effort is configured in the chat.</p>
      <LocalModelsPanel />
      <Section title="BUILDER">
        <Row label="Model">
          <Select value={models.chatgpt.model} options={available(catalog.chatgpt.models)} onChange={(value) => void selectModel('chatgpt', value)} />
        </Row>
      </Section>
      <Section title="REVIEWER">
        <Row label="Model">
          <Select value={models.deepseek.model} options={available(catalog.deepseek.models)} onChange={(value) => void selectModel('deepseek', value)} />
        </Row>
      </Section>
      <Section title="RESEARCH">
        <Row label="Model">
          <Select value={models.gemini.model} options={available(catalog.gemini.models)} onChange={(value) => void selectModel('gemini', value)} />
        </Row>
      </Section>
      <Section title="3D GENERATOR">
        <Row label="Version">
          <Select value={models.hunyuan.version} options={available(catalog.hunyuan.versions)} onChange={(value) => void selectModel('hunyuan', value)} />
        </Row>
        <p className="text-xs text-ink-300 py-2">Quality follows the options available in the provider window.</p>
      </Section>
      <Section title="ROUTING">
        <Row label="Smart Routing" hint="Route text work to the configured providers or the available local model">
          <Toggle checked={models.smartRouting} onChange={(value) => void setRouting(value)} />
        </Row>
      </Section>
    </div>
  );
}

function LocalModelsPanel() {
  const [state, setState] = useState<LocalAIState | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => getApi().getLocalAIState().then((value) => { if (active) setState(value); }).catch((error) => frontendDiagnostics.capture(error, 'local-ai', 'Unable to load local model status'));
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <Section title="LOCAL AI">
    <Row label={state?.model || 'Local model'} hint="Runs one inference at a time. Uses Qwen Coder 7B for building and Qwen3 4B for review when both are installed. Models are unloaded before switching. Vulkan is tried first, then CPU. Web research and 3D generation require their own providers.">
      <span className="text-xs text-ink-50">{state?.available ? state.running ? 'Running' : 'Ready' : 'Setup needed'}</span>
    </Row>
    {state?.models?.map((model) => <div key={model.name} className="flex justify-between py-2 text-xs"><span className="text-ink-100">{model.name}</span><span className="text-ink-300">{model.installed ? 'Installed' : 'Setup needed'}</span></div>)}
    <div className="flex items-center justify-between gap-4 pt-3">
      <p className="text-xs text-ink-300" role="status">{state?.setup.detail || 'Checking local tools'}</p>
      <button disabled={busy || state?.setup.state === 'INSTALLING'} onClick={async () => {
        setBusy(true);
        try { await getApi().prepareLocalAI(); setState(await getApi().getLocalAIState()); }
        catch (error) { frontendDiagnostics.capture(error, 'local-ai', 'Local setup failed'); }
        finally { setBusy(false); }
      }} className="shrink-0 px-3 py-2 text-xs border border-ink-500 text-ink-50 hover:border-zen-red disabled:opacity-50">{state?.setup.state === 'INSTALLING' ? 'Preparing…' : state?.available ? 'Verify tools' : 'Prepare local AI'}</button>
    </div>
  </Section>;
}

function LinksTab({ connections }: { connections: ConnectionInfo }) {
  const [loginModal, setLoginModal] = useState<ProviderId | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);
  const setConnections = useStore((s) => s.setConnections);
  const setAgents = useStore((s) => s.setAgents);
  const labels: { key: keyof ConnectionInfo; name: string; provider?: ProviderId }[] = [
    { key: 'bridge', name: 'Bridge' },
    { key: 'browser', name: 'Browser' },
    { key: 'chatgpt', name: 'Builder', provider: 'chatgpt' },
    { key: 'deepseek', name: 'Reviewer', provider: 'deepseek' },
    { key: 'gemini', name: 'Research', provider: 'gemini' },
    { key: 'hunyuan', name: '3D Generator', provider: 'hunyuan' },
    { key: 'studio', name: 'Studio' },
  ];

  const handleLogin = async () => {
    if (!loginModal || loggingIn) return;
    setLoggingIn(true);
    try {
      await getApi().loginProvider(loginModal);
      const [nextConnections, nextAgents] = await Promise.all([getApi().getConnections(), getApi().getAgents()]);
      setConnections(nextConnections);
      setAgents(nextAgents);
      setLoginModal(null);
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', `Failed to open ${loginModal} login`);
    } finally {
      setLoggingIn(false);
    }
  };

  return (
    <div className="p-6 max-w-2xl mx-auto w-full space-y-6 animate-fade-in">
      <Section title="CONNECTIONS">
        {labels.map(({ key, name, provider }) => {
          const status = connections[key];
          return (
            <div key={key} className="flex items-center justify-between py-1.5 border-b border-ink-700">
              <span className="text-xs text-ink-100">{name}</span>
              <div className="flex items-center gap-2">
                <StatusBadge status={status} />
                {key === 'studio' && <button onClick={() => void getApi().refreshStudio().catch((error) => frontendDiagnostics.capture(error, 'studio', 'Studio reconnection failed'))} className="px-2 h-7 text-xs border border-ink-500 text-ink-50 hover:border-zen-red">Reconnect</button>}
                {provider && (
                  <button onClick={() => setLoginModal(provider)} className="px-2 h-6 text-2xs uppercase tracking-wider text-ink-50 border border-ink-500 hover:bg-ink-800 transition-colors">LOGIN</button>
                )}
                {status === 'OFF' && isMockMode() && (
                  <Tooltip content="Retry connection">
                    <button
                      onClick={() => {
                        const mockApi = getMockApi();
                        if (!mockApi) return;
                        mockApi.setMockConnection(key, 'CONNECTING');
                        window.setTimeout(() => mockApi.setMockConnection(key, 'READY'), 800);
                      }}
                      className="px-2 h-6 text-2xs uppercase tracking-wider text-ink-300 border border-ink-600 hover:bg-ink-800 transition-colors"
                    >
                      CONNECT
                    </button>
                  </Tooltip>
                )}
              </div>
            </div>
          );
        })}
      </Section>
      <Modal open={!!loginModal} onClose={() => setLoginModal(null)} title="LOGIN REQUIRED" width="w-80">
        <div className="space-y-4">
          <p className="text-xs text-ink-100 uppercase tracking-wider">{labels.find((label) => label.key === loginModal)?.name}</p>
          <button disabled={loggingIn} onClick={() => void handleLogin()} className="w-full h-8 text-xs uppercase tracking-wider text-ink-0 bg-ink-700 border border-ink-500 hover:bg-ink-600 transition-colors disabled:opacity-50">{loggingIn ? 'OPENING' : 'LOGIN'}</button>
        </div>
      </Modal>
    </div>
  );
}

function LibraryTab() {
  const tools = useStore((s) => s.tools);
  const setTools = useStore((s) => s.setTools);
  useEffect(() => {
    let active = true;
    const refresh = () => getApi().getTools().then((items) => { if (active) setTools(items); })
      .catch((error) => frontendDiagnostics.capture(error, 'tools', 'Unable to refresh tools'));
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [setTools]);
  const installed = tools.filter((tool) => tool.status === 'INSTALLED').length;

  return (
    <div className="p-6 max-w-2xl mx-auto w-full space-y-4 animate-fade-in">
      <LocalModelsPanel />
      <div className="flex items-center justify-between">
        <span className="text-2xs uppercase tracking-widest text-ink-300">UPSTREAM TOOLCHAIN</span>
        <span className="text-2xs font-mono text-ink-400">{installed}/{tools.length || 0}</span>
      </div>
      <div className="border-t border-ink-700">
        {tools.length === 0 ? (
          <div className="py-4 text-center text-2xs text-ink-400 uppercase">Toolchain not hydrated</div>
        ) : tools.map((tool) => (
          <div key={tool.id} className="grid grid-cols-[1fr_auto] gap-3 py-2 border-b border-ink-700">
            <div className="min-w-0">
              <div className="text-xs text-ink-100 truncate">{tool.name}</div>
              <div className="text-2xs text-ink-400 break-words">{tool.status === 'INSTALLED' ? tool.description || tool.category : tool.reason || tool.description}</div>
            </div>
            <span className="text-xs text-ink-300 self-center">{tool.status === 'INSTALLED' ? 'Installed' : tool.status === 'OPTIONAL' ? 'Optional' : 'Not installed'}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LogsTab() {
  const diagnostics = useStore((s) => s.diagnostics);
  return (
    <div className="p-4 max-w-2xl space-y-4 animate-fade-in">
      <Section title="DIAGNOSTICS">
        {diagnostics.length === 0 ? (
          <div className="py-4 text-center text-2xs text-ink-400 uppercase">No diagnostics</div>
        ) : diagnostics.map((diagnostic) => <DiagnosticRow key={diagnostic.id} diagnostic={diagnostic} />)}
      </Section>
    </div>
  );
}

function DiagnosticRow({ diagnostic }: { diagnostic: Diagnostic }) {
  const [open, setOpen] = useState(false);
  const status = diagnostic.severity === 'critical' || diagnostic.severity === 'error' ? 'ERR' : diagnostic.severity === 'warning' ? 'LOGIN' : 'READY';
  return (
    <button onClick={() => setOpen((value) => !value)} className="block w-full text-left py-1.5 border-b border-ink-700 hover:bg-ink-850 transition-colors">
      <div className="flex items-start gap-3 px-1">
        <StatusDot status={status} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-ink-300">{diagnostic.source}</span>
            {diagnostic.file && <span className="text-2xs font-mono text-ink-400">{diagnostic.file}:{diagnostic.line ?? ''}</span>}
            {(diagnostic.occurrenceCount ?? 1) > 1 && <span className="text-2xs text-ink-400">×{diagnostic.occurrenceCount}</span>}
          </div>
          <p className="text-xs text-ink-100 mt-0.5 truncate">{diagnostic.message}</p>
          {open && (
            <div className="mt-2 space-y-1 text-2xs text-ink-300 font-mono whitespace-pre-wrap">
              {diagnostic.function && <div>fn: {diagnostic.function}</div>}
              {diagnostic.probableCause && <div>cause: {diagnostic.probableCause}</div>}
              {diagnostic.impact && <div>impact: {diagnostic.impact}</div>}
              {diagnostic.recovery && <div>recovery: {diagnostic.recovery}</div>}
              {diagnostic.stack && <div className="text-ink-400">{diagnostic.stack}</div>}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-2xs uppercase tracking-widest text-ink-300 mb-2">{title}</h3>
      <div className="space-y-0">{children}</div>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(180px,260px)] items-center gap-6 py-3 border-b border-ink-700">
      <div className="min-w-0">
        <span className="text-xs font-medium text-ink-50">{label}</span>
        {hint && <p className="mt-1 text-xs leading-relaxed text-ink-300">{hint}</p>}
      </div>
      <div className="flex items-center justify-end gap-2 min-w-0 [&>div]:w-full">{children}</div>
    </div>
  );
}

function EmptyState() {
  return <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider animate-pulse-soft">Loading</div>;
}
