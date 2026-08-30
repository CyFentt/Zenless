import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi, isMockMode, getMockApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tabs, Toggle, Select } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import { StatusDot, StatusBadge } from '@/components/StatusDot';
import { Modal } from '@/components/Modal';
import type { ConnectionInfo, Diagnostic, ModelCatalog, ModelSettings, ProviderId, Settings } from '@/types';

type SettingsTab = 'general' | 'models' | 'links' | 'logs';

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
          { id: 'logs', label: 'LOGS' },
        ]}
        active={tab}
        onChange={(t) => setTab(t as SettingsTab)}
      />
      <div className="flex-1 overflow-y-auto scrollbar-zen">
        {tab === 'general' && <GeneralTab settings={settings} onChange={setSettings} />}
        {tab === 'models' && <ModelsTab settings={settings} catalog={catalog} onChange={setSettings} />}
        {tab === 'links' && <LinksTab connections={connections} />}
        {tab === 'logs' && <LogsTab />}
      </div>
    </div>
  );
}

function GeneralTab({ settings, onChange }: { settings: Settings | null; onChange: (s: Settings) => void }) {
  if (!settings) return <EmptyState />;

  const persist = async (patch: Partial<Settings>) => {
    try {
      const next = await getApi().updateSettings(patch);
      onChange(next);
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', 'Failed to update general settings');
    }
  };

  return (
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="BEHAVIOR">
        <Row label="Auto Approve" hint="Automatically approve low-risk changes">
          <Toggle checked={settings.autoApprove} onChange={(value) => void persist({ autoApprove: value })} />
        </Row>
        <Row label="Max Revisions" hint="Maximum revision attempts per job">
          <input
            type="number"
            value={settings.maxRevisions}
            min={1}
            max={10}
            onChange={(event) => void persist({ maxRevisions: Number.parseInt(event.target.value, 10) || 1 })}
            className="w-12 h-6 text-2xs text-center text-ink-50 bg-ink-800 border border-ink-600 focus:border-ink-500"
          />
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

  const persistModels = async (nextModels: ModelSettings) => {
    try {
      const next = await getApi().updateSettings({ models: nextModels });
      onChange(next);
    } catch (error) {
      frontendDiagnostics.capture(error, 'settings', 'Failed to update model settings');
    }
  };

  const selectModel = async (provider: 'chatgpt' | 'deepseek' | 'hunyuan', value: string) => {
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
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="BUILDER">
        <Row label="Model">
          <Select value={models.chatgpt.model} options={available(catalog.chatgpt.models)} onChange={(value) => void selectModel('chatgpt', value)} />
        </Row>
        <Row label="Reasoning" hint="Enable extended reasoning">
          <Toggle checked={models.chatgpt.reasoning} onChange={(value) => void persistModels({ ...models, chatgpt: { ...models.chatgpt, reasoning: value } })} />
        </Row>
      </Section>
      <Section title="REVIEWER">
        <Row label="Model">
          <Select value={models.deepseek.model} options={available(catalog.deepseek.models)} onChange={(value) => void selectModel('deepseek', value)} />
        </Row>
        <Row label="Reasoning" hint="Enable extended reasoning">
          <Toggle checked={models.deepseek.reasoning} onChange={(value) => void persistModels({ ...models, deepseek: { ...models.deepseek, reasoning: value } })} />
        </Row>
      </Section>
      <Section title="3D GENERATOR">
        <Row label="Version">
          <Select value={models.hunyuan.version} options={available(catalog.hunyuan.versions)} onChange={(value) => void selectModel('hunyuan', value)} />
        </Row>
        <Row label="Quality">
          <Select value={models.hunyuan.quality} options={available(catalog.hunyuan.qualities)} onChange={(value) => void persistModels({ ...models, hunyuan: { ...models.hunyuan, quality: value } })} />
        </Row>
      </Section>
      <Section title="ROUTING">
        <Row label="Smart Routing" hint="Automatically select best model per task">
          <Toggle checked={models.smartRouting} onChange={(value) => void setRouting(value)} />
        </Row>
      </Section>
    </div>
  );
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
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="CONNECTIONS">
        {labels.map(({ key, name, provider }) => {
          const status = connections[key];
          return (
            <div key={key} className="flex items-center justify-between py-1.5 border-b border-ink-700">
              <span className="text-xs text-ink-100">{name}</span>
              <div className="flex items-center gap-2">
                <StatusBadge status={status} />
                {(status === 'LOGIN' || status === 'OFF' || status === 'ERR') && provider && (
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
    <Tooltip content={hint ?? label} side="left">
      <div className="flex items-center justify-between py-2 border-b border-ink-700">
        <span className="text-2xs uppercase tracking-wider text-ink-300">{label}</span>
        {children}
      </div>
    </Tooltip>
  );
}

function EmptyState() {
  return <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider animate-pulse-soft">Loading</div>;
}
