import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import { Select, Segmented, Toggle } from '@/components/Tabs';
import { StatusBadge } from '@/components/StatusDot';
import { getApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { useStore } from '@/store';
import {
  PROVIDER_NAMES,
  type ModelCatalog,
  type ModelSettings,
  type ProviderDescriptor,
  type ProviderId,
  type Settings,
  type TaskOptions,
} from '@/types';

interface Props {
  options: TaskOptions;
  initialView?: PanelView;
  onChange: (options: TaskOptions) => void;
  onClose: () => void;
}

type PanelView = 'task' | 'providers' | 'defaults';

const PROVIDER_IDS: ProviderId[] = ['chatgpt', 'deepseek', 'hunyuan'];

export function TaskOptionsPanel({ options, initialView = 'task', onChange, onClose }: Props) {
  const settings = useStore((state) => state.settings);
  const providers = useStore((state) => state.providers);
  const connections = useStore((state) => state.connections);
  const setSettings = useStore((state) => state.setSettings);
  const setProviders = useStore((state) => state.setProviders);
  const setConnections = useStore((state) => state.setConnections);
  const setAgents = useStore((state) => state.setAgents);
  const [view, setView] = useState<PanelView>(initialView);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([getApi().getSettings(), getApi().getProviders(true), getApi().getModels(true)])
      .then(([nextSettings, nextProviders, nextCatalog]) => {
        if (!active) return;
        setSettings(nextSettings);
        setProviders(nextProviders);
        setCatalog(nextCatalog);
      })
      .catch((reason) => {
        frontendDiagnostics.capture(reason, 'chat-controls', 'Failed to load workspace controls');
        if (active) setError('Controls are temporarily unavailable.');
      });
    return () => { active = false; };
  }, [setProviders, setSettings]);

  const run = async (key: string, action: () => Promise<void>) => {
    if (pending) return;
    setPending(key);
    setError('');
    try {
      await action();
    } catch (reason) {
      frontendDiagnostics.capture(reason, 'chat-controls', 'Workspace control failed');
      setError(reason instanceof Error && reason.message ? reason.message : 'The requested change could not be verified.');
    } finally {
      setPending('');
    }
  };

  const refresh = () => run('refresh', async () => {
    const [nextProviders, nextCatalog, nextConnections, nextAgents] = await Promise.all([
      getApi().getProviders(true),
      getApi().getModels(true),
      getApi().getConnections(),
      getApi().getAgents(),
    ]);
    setProviders(nextProviders);
    setCatalog(nextCatalog);
    setConnections(nextConnections);
    setAgents(nextAgents);
  });

  const updateProvider = (provider: ProviderId, selection: { model?: string; mode?: string }) => run(`${provider}:${selection.model ?? selection.mode}`, async () => {
    const next = await getApi().selectProvider(provider, selection);
    setProviders(providers.some((item) => item.providerId === provider)
      ? providers.map((item) => item.providerId === provider ? next : item)
      : [...providers, next]);
    const [nextSettings, nextCatalog] = await Promise.all([getApi().getSettings(), getApi().getModels(true)]);
    setSettings(nextSettings);
    setCatalog(nextCatalog);
  });

  const login = (provider: ProviderId) => run(`${provider}:login`, async () => {
    setConnections({ [provider]: 'CONNECTING' });
    await getApi().loginProvider(provider);
  });

  const persist = (patch: Partial<Settings>) => run('defaults', async () => {
    setSettings(await getApi().updateSettings(patch));
  });

  const setTask = <K extends keyof TaskOptions>(key: K, value: TaskOptions[K]) => {
    onChange({ ...options, [key]: value });
  };

  return (
    <aside className="w-[22rem] shrink-0 bg-ink-900 border-l border-ink-600 animate-panel-in flex flex-col shadow-panel">
      <div className="flex items-center justify-between px-3 h-10 border-b border-ink-600 shrink-0">
        <span className="text-2xs uppercase tracking-[0.22em] text-ink-0">Controls</span>
        <div className="flex items-center gap-1">
          <button onClick={() => void refresh()} disabled={Boolean(pending)} className="zen-icon-button" aria-label="Refresh provider state">
            <RefreshCw size={12} className={pending === 'refresh' ? 'animate-spin' : ''} />
          </button>
          <button onClick={onClose} className="zen-icon-button" aria-label="Close controls">
            <X size={13} />
          </button>
        </div>
      </div>
      <div className="px-3 pt-3">
        <Segmented
          options={[
            { id: 'task', label: 'Task' },
            { id: 'providers', label: 'Providers' },
            { id: 'defaults', label: 'Defaults' },
          ]}
          active={view}
          onChange={(value) => setView(value as PanelView)}
        />
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-zen p-3">
        {view === 'task' && <TaskControls options={options} setTask={setTask} onChange={onChange} />}
        {view === 'providers' && (
          <ProviderControls
            providers={providers}
            connections={connections}
            settings={settings}
            catalog={catalog}
            pending={pending}
            onLogin={login}
            onSelection={updateProvider}
          />
        )}
        {view === 'defaults' && <DefaultControls settings={settings} pending={pending} onPersist={persist} />}
        {error && <div role="alert" className="mt-3 border border-ink-400 bg-ink-800 px-2.5 py-2 text-2xs leading-relaxed text-ink-25">{error}</div>}
      </div>
    </aside>
  );
}

function TaskControls({
  options,
  setTask,
  onChange,
}: {
  options: TaskOptions;
  setTask: <K extends keyof TaskOptions>(key: K, value: TaskOptions[K]) => void;
  onChange: (options: TaskOptions) => void;
}) {
  return (
    <div className="space-y-5 animate-fade-in">
      <Section title="Workflow">
        <OptionRow label="Visual"><Toggle checked={options.visualFirst} onChange={(value) => setTask('visualFirst', value || options.create3D)} /></OptionRow>
        <OptionRow label="3D"><Toggle checked={options.create3D} onChange={(value) => onChange({ ...options, create3D: value, visualFirst: value || options.visualFirst })} /></OptionRow>
        <OptionRow label="Review"><Toggle checked={options.review} onChange={(value) => setTask('review', value)} /></OptionRow>
        <OptionRow label="Auto Test"><Toggle checked={options.autoTest} onChange={(value) => setTask('autoTest', value)} /></OptionRow>
        <OptionRow label="Auto Fix"><Toggle checked={options.autoFix} onChange={(value) => setTask('autoFix', value)} /></OptionRow>
        <OptionRow label="Approval"><Toggle checked={options.approval} onChange={(value) => setTask('approval', value)} /></OptionRow>
      </Section>
      <Section title="Depth">
        <OptionRow label="Research">
          <Select value={options.research ?? 'AUTO'} options={['AUTO', 'ON', 'OFF'].map((id) => ({ id, label: id }))} onChange={(value) => setTask('research', value as TaskOptions['research'])} />
        </OptionRow>
        <OptionRow label="Effort">
          <Select value={options.effort ?? 'AUTO'} options={['AUTO', 'MIN', 'MED', 'MAX'].map((id) => ({ id, label: id }))} onChange={(value) => setTask('effort', value as TaskOptions['effort'])} />
        </OptionRow>
        <OptionRow label="Context">
          <Select value={options.chatMode ?? 'PROJECT'} options={[{ id: 'PROJECT', label: 'PROJECT' }, { id: 'TEMP', label: 'TEMP' }]} onChange={(value) => setTask('chatMode', value as TaskOptions['chatMode'])} />
        </OptionRow>
        <OptionRow label="Risk">
          <Select value={options.risk} options={[{ id: 'low', label: 'LOW' }, { id: 'medium', label: 'MED' }, { id: 'high', label: 'HIGH' }]} onChange={(value) => setTask('risk', value as TaskOptions['risk'])} />
        </OptionRow>
        <OptionRow label="Revisions"><NumberInput value={options.revisions} onChange={(value) => setTask('revisions', value)} /></OptionRow>
        <OptionRow label="Fix Attempts"><NumberInput value={options.fixAttempts} onChange={(value) => setTask('fixAttempts', value)} /></OptionRow>
      </Section>
    </div>
  );
}

function ProviderControls({
  providers,
  connections,
  settings,
  catalog,
  pending,
  onLogin,
  onSelection,
}: {
  providers: ProviderDescriptor[];
  connections: ReturnType<typeof useStore.getState>['connections'];
  settings: Settings | null;
  catalog: ModelCatalog | null;
  pending: string;
  onLogin: (provider: ProviderId) => Promise<void>;
  onSelection: (provider: ProviderId, selection: { model?: string; mode?: string }) => Promise<void>;
}) {
  const visible = useMemo(() => PROVIDER_IDS.map((id) => providers.find((provider) => provider.providerId === id)).filter(Boolean) as ProviderDescriptor[], [providers]);
  return (
    <div className="space-y-3 animate-fade-in">
      {visible.map((provider) => {
        const id = provider.providerId as ProviderId;
        const status = connections[id];
        const models = modelOptions(id, catalog);
        const currentModel = selectedModel(id, settings);
        const mode = String(provider.selection?.mode ?? catalogEntry(id, catalog)?.selection?.mode ?? provider.modes[0]?.id ?? '');
        const capabilities = provider.liveCapabilities ?? catalogEntry(id, catalog)?.liveCapabilities ?? provider.modes.find((item) => item.id === mode)?.capabilities;
        const requiresLogin = status === 'LOGIN' || status === 'OFF' || provider.authState === 'LOGIN_REQUIRED' || provider.authState === 'UNKNOWN';
        return (
          <section key={id} className="border border-ink-650 bg-ink-850 p-3 transition-colors hover:border-ink-500">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-xs uppercase tracking-[0.16em] text-ink-0">{PROVIDER_NAMES[id]}</h3>
                <p className="mt-1 truncate text-2xs uppercase tracking-wider text-ink-300">{provider.roles.map(roleLabel).join(' · ') || 'Unassigned'}</p>
              </div>
              <StatusBadge status={status} label={availabilityLabel(provider, status)} />
            </div>
            {requiresLogin ? (
              <button disabled={Boolean(pending)} onClick={() => void onLogin(id)} className="zen-button mt-3 w-full">
                {pending === `${id}:login` ? 'Opening' : 'Login'}
              </button>
            ) : (
              <div className="mt-3 space-y-2.5">
                {models.length > 0 && (
                  <Control label="Model">
                    <Select value={currentModel} options={models} onChange={(value) => void onSelection(id, { model: value })} />
                  </Control>
                )}
                {provider.modes.length > 1 && capabilities?.supportsModeSelection && (
                  <Control label="Mode">
                    <Select value={mode} options={provider.modes.map((item) => ({ id: item.id, label: item.label }))} onChange={(value) => void onSelection(id, { mode: value })} />
                  </Control>
                )}
                <div className="flex flex-wrap gap-1 pt-1">
                  {capabilityLabels(capabilities).map((label) => <span key={label} className="border border-ink-600 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-ink-200">{label}</span>)}
                  {capabilities && !capabilities.supportsFiles && <span className="border border-ink-600 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-ink-50">Text fallback</span>}
                </div>
              </div>
            )}
            {provider.availabilityState && !['UNKNOWN', 'READY'].includes(provider.availabilityState) && provider.detail && (
              <p className="mt-2 text-2xs leading-relaxed text-ink-100">{provider.detail}</p>
            )}
          </section>
        );
      })}
      {visible.length === 0 && <Empty label="Provider state unavailable" />}
      <p className="border-t border-ink-700 pt-3 text-2xs leading-relaxed text-ink-300">If a quota or model becomes unavailable, switch its model or disable Review, Visual, or 3D for this task.</p>
    </div>
  );
}

function DefaultControls({ settings, pending, onPersist }: { settings: Settings | null; pending: string; onPersist: (patch: Partial<Settings>) => Promise<void> }) {
  if (!settings) return <Empty label="Loading defaults" />;
  const models = settings.models;
  const persistModels = (next: ModelSettings) => onPersist({ models: next });
  return (
    <div className="space-y-5 animate-fade-in">
      <Section title="Behavior">
        <OptionRow label="Auto Approve"><Toggle checked={settings.autoApprove} onChange={(value) => void onPersist({ autoApprove: value })} /></OptionRow>
        <OptionRow label="Max Revisions"><NumberInput value={settings.maxRevisions} onChange={(value) => void onPersist({ maxRevisions: value })} /></OptionRow>
      </Section>
      <Section title="Routing">
        <OptionRow label="Smart Routing"><Toggle checked={models.smartRouting} onChange={(value) => void persistModels({ ...models, smartRouting: value })} /></OptionRow>
        <OptionRow label="Builder Reasoning"><Toggle checked={models.chatgpt.reasoning} onChange={(value) => void persistModels({ ...models, chatgpt: { ...models.chatgpt, reasoning: value } })} /></OptionRow>
        <OptionRow label="Reviewer Reasoning"><Toggle checked={models.deepseek.reasoning} onChange={(value) => void persistModels({ ...models, deepseek: { ...models.deepseek, reasoning: value } })} /></OptionRow>
      </Section>
      {pending === 'defaults' && <p className="text-2xs uppercase tracking-wider text-ink-300 animate-pulse-soft">Saving</p>}
    </div>
  );
}

function catalogEntry(provider: ProviderId, catalog: ModelCatalog | null) {
  return catalog?.[provider];
}

function modelOptions(provider: ProviderId, catalog: ModelCatalog | null) {
  const items = provider === 'hunyuan'
    ? catalog?.hunyuan.versions
    : provider === 'chatgpt'
      ? catalog?.chatgpt.models
      : catalog?.deepseek.models;
  const available = (items ?? []).filter((item) => item.available !== false);
  const live = available.filter((item) => item.source === 'LIVE');
  return live.length > 0 ? live : available.filter((item) => item.source !== 'CONFIGURED');
}

function selectedModel(provider: ProviderId, settings: Settings | null) {
  if (!settings) return 'auto';
  return provider === 'hunyuan' ? settings.models.hunyuan.version : settings.models[provider].model;
}

function roleLabel(role: string) {
  return role === 'THREED' ? '3D' : role.charAt(0) + role.slice(1).toLocaleLowerCase();
}

function availabilityLabel(provider: ProviderDescriptor, fallback: string) {
  const state = provider.availabilityState;
  if (!state || state === 'UNKNOWN') return fallback;
  return state.replace(/_/g, ' ');
}

function capabilityLabels(capabilities: ProviderDescriptor['liveCapabilities']) {
  if (!capabilities) return [];
  return [
    capabilities.supportsReasoning && 'Reasoning',
    capabilities.supportsSearch && 'Search',
    capabilities.supportsFiles && 'Files',
    capabilities.supportsVision && 'Vision',
  ].filter(Boolean) as string[];
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-1 text-2xs uppercase tracking-[0.2em] text-ink-300">{title}</h3><div>{children}</div></section>;
}

function OptionRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex min-h-9 items-center justify-between gap-3 border-b border-ink-700 py-1.5"><span className="text-2xs uppercase tracking-wider text-ink-200">{label}</span>{children}</div>;
}

function Control({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-[4rem_1fr] items-center gap-2"><span className="text-2xs uppercase tracking-wider text-ink-300">{label}</span>{children}</div>;
}

function NumberInput({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return <input type="number" value={value} min={1} max={10} onChange={(event) => onChange(Math.max(1, Math.min(10, Number.parseInt(event.target.value, 10) || 1)))} className="h-7 w-12 border border-ink-600 bg-ink-800 text-center text-2xs text-ink-25 focus:border-ink-300" />;
}

function Empty({ label }: { label: string }) {
  return <div className="py-8 text-center text-2xs uppercase tracking-wider text-ink-400 animate-pulse-soft">{label}</div>;
}
