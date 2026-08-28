import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi, isMockMode, getMockApi } from '@/services';
import { Tabs, Toggle, Select } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import { StatusDot, StatusBadge } from '@/components/StatusDot';
import { Modal } from '@/components/Modal';
import type { Settings, ConnectionInfo } from '@/types';

type SettingsTab = 'general' | 'models' | 'links' | 'logs';

export function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('general');
  const settings = useStore((s) => s.settings);
  const setSettings = useStore((s) => s.setSettings);
  const connections = useStore((s) => s.connections);

  useEffect(() => {
    getApi().getSettings().then(setSettings).catch(() => {});
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
        {tab === 'models' && <ModelsTab settings={settings} onChange={setSettings} />}
        {tab === 'links' && <LinksTab connections={connections} />}
        {tab === 'logs' && <LogsTab />}
      </div>
    </div>
  );
}

function GeneralTab({ settings, onChange }: { settings: Settings | null; onChange: (s: Settings) => void }) {
  if (!settings) return <EmptyState />;
  return (
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="BEHAVIOR">
        <Row label="Auto Approve" hint="Automatically approve low-risk changes">
          <Toggle checked={settings.autoApprove} onChange={(v) => onChange({ ...settings, autoApprove: v })} />
        </Row>
        <Row label="Max Revisions" hint="Maximum revision attempts per job">
          <input
            type="number"
            value={settings.maxRevisions}
            min={1}
            max={10}
            onChange={(e) => onChange({ ...settings, maxRevisions: parseInt(e.target.value) || 1 })}
            className="w-12 h-6 text-2xs text-center text-ink-50 bg-ink-800 border border-ink-600 focus:border-ink-500"
          />
        </Row>
      </Section>
      <Section title="CONNECTION">
        <Row label="Bridge Port" hint="Local bridge server port">
          <input
            type="number"
            value={settings.bridgePort}
            onChange={(e) => onChange({ ...settings, bridgePort: parseInt(e.target.value) || 8787 })}
            className="w-16 h-6 text-2xs text-center text-ink-50 bg-ink-800 border border-ink-600 focus:border-ink-500"
          />
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

function ModelsTab({ settings, onChange }: { settings: Settings | null; onChange: (s: Settings) => void }) {
  if (!settings) return <EmptyState />;
  const m = settings.models;

  const chatgptModels = [
    { id: 'gpt-4o', label: 'GPT-4o' },
    { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
    { id: 'o1', label: 'O1' },
    { id: 'o1-mini', label: 'O1 Mini' },
  ];
  const deepseekModels = [
    { id: 'deepseek-v3', label: 'DeepSeek V3' },
    { id: 'deepseek-r1', label: 'DeepSeek R1' },
    { id: 'deepseek-coder', label: 'DeepSeek Coder' },
  ];
  const hunyuanVersions = [
    { id: 'hunyuan-3d-1.0', label: 'Hunyuan 3D 1.0' },
    { id: 'hunyuan-3d-2.0', label: 'Hunyuan 3D 2.0' },
  ];
  const qualityOptions = [
    { id: 'draft', label: 'DRAFT' },
    { id: 'standard', label: 'STANDARD' },
    { id: 'high', label: 'HIGH' },
  ];

  const update = (patch: Partial<typeof m>) => {
    onChange({ ...settings, models: { ...m, ...patch } });
  };

  return (
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="ChatGPT">
        <Row label="Model">
          <Select value={m.chatgpt.model} options={chatgptModels} onChange={(v) => update({ chatgpt: { ...m.chatgpt, model: v } })} />
        </Row>
        <Row label="Reasoning" hint="Enable extended reasoning">
          <Toggle checked={m.chatgpt.reasoning} onChange={(v) => update({ chatgpt: { ...m.chatgpt, reasoning: v } })} />
        </Row>
      </Section>
      <Section title="DeepSeek">
        <Row label="Model">
          <Select value={m.deepseek.model} options={deepseekModels} onChange={(v) => update({ deepseek: { ...m.deepseek, model: v } })} />
        </Row>
        <Row label="Reasoning" hint="Enable extended reasoning">
          <Toggle checked={m.deepseek.reasoning} onChange={(v) => update({ deepseek: { ...m.deepseek, reasoning: v } })} />
        </Row>
      </Section>
      <Section title="Hunyuan">
        <Row label="Version">
          <Select value={m.hunyuan.version} options={hunyuanVersions} onChange={(v) => update({ hunyuan: { ...m.hunyuan, version: v } })} />
        </Row>
        <Row label="Quality">
          <Select value={m.hunyuan.quality} options={qualityOptions} onChange={(v) => update({ hunyuan: { ...m.hunyuan, quality: v } })} />
        </Row>
      </Section>
      <Section title="ROUTING">
        <Row label="Smart Routing" hint="Automatically select best model per task">
          <Toggle checked={m.smartRouting} onChange={(v) => update({ smartRouting: v })} />
        </Row>
      </Section>
    </div>
  );
}

function LinksTab({ connections }: { connections: ConnectionInfo }) {
  const [loginModal, setLoginModal] = useState<string | null>(null);
  const labels: { key: keyof ConnectionInfo; name: string }[] = [
    { key: 'bridge', name: 'Bridge' },
    { key: 'browser', name: 'Browser' },
    { key: 'chatgpt', name: 'ChatGPT' },
    { key: 'deepseek', name: 'DeepSeek' },
    { key: 'hunyuan', name: 'Hunyuan' },
    { key: 'studio', name: 'Studio' },
  ];

  const handleLogin = () => {
    const mockApi = getMockApi();
    if (mockApi && loginModal) {
      mockApi.setMockConnection(loginModal as keyof ConnectionInfo, 'READY');
      mockApi.setMockAgentStatus(loginModal, 'READY');
    }
    setLoginModal(null);
  };

  return (
    <div className="p-4 max-w-md space-y-4 animate-fade-in">
      <Section title="CONNECTIONS">
        {labels.map(({ key, name }) => {
          const status = connections[key];
          return (
            <div key={key} className="flex items-center justify-between py-1.5 border-b border-ink-700">
              <span className="text-xs text-ink-100">{name}</span>
              <div className="flex items-center gap-2">
                <StatusBadge status={status} />
                {status === 'LOGIN' && (
                  <button onClick={() => setLoginModal(key)} className="px-2 h-6 text-2xs uppercase tracking-wider text-ink-50 border border-ink-500 hover:bg-ink-800 transition-colors">
                    LOGIN
                  </button>
                )}
                {status === 'OFF' && (
                  <Tooltip content="Retry connection">
                    <button
                      onClick={() => {
                        const mockApi = getMockApi();
                        if (mockApi) {
                          mockApi.setMockConnection(key, 'CONNECTING');
                          setTimeout(() => mockApi.setMockConnection(key, 'READY'), 1500);
                        }
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
          <p className="text-xs text-ink-100 uppercase tracking-wider">{labels.find((l) => l.key === loginModal)?.name}</p>
          <p className="text-2xs text-ink-300">LOGIN REQUIRED</p>
          <button onClick={handleLogin} className="w-full h-8 text-xs uppercase tracking-wider text-ink-0 bg-ink-700 border border-ink-500 hover:bg-ink-600 transition-colors">
            LOGIN
          </button>
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
        ) : (
          diagnostics.map((d) => (
            <div key={d.id} className="flex items-start gap-3 py-1.5 border-b border-ink-700">
              <StatusDot status={d.severity === 'error' ? 'ERR' : d.severity === 'warning' ? 'LOGIN' : 'READY'} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-2xs uppercase tracking-wider text-ink-300">{d.source}</span>
                  {d.file && <span className="text-2xs font-mono text-ink-400">{d.file}:{d.line ?? ''}</span>}
                </div>
                <p className="text-xs text-ink-100 mt-0.5">{d.message}</p>
              </div>
            </div>
          ))
        )}
      </Section>
    </div>
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
