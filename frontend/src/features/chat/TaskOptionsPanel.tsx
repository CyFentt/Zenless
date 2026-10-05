import { X } from 'lucide-react';
import { Toggle, Select } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import type { TaskOptions } from '@/types';

interface Props {
  options: TaskOptions;
  onChange: (opts: TaskOptions) => void;
  onClose: () => void;
}

export function TaskOptionsPanel({ options, onChange, onClose }: Props) {
  const set = <K extends keyof TaskOptions>(key: K, value: TaskOptions[K]) => {
    onChange({ ...options, [key]: value });
  };

  return (
    <div className="w-80 max-w-[45%] shrink-0 bg-ink-900 border-l border-ink-600 animate-slide-right flex flex-col">
      <div className="flex items-center justify-between px-3 h-9 border-b border-ink-600 shrink-0">
        <span className="text-2xs uppercase tracking-widest text-ink-0 font-medium">OPTIONS</span>
        <button onClick={onClose} className="text-ink-300 hover:text-ink-0" aria-label="Close">
          <X size={12} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-zen p-3 space-y-3">
        <OptionRow label="Visual First" hint="Required while 3D generation is enabled">
          <Toggle hideLabel
            checked={options.visualFirst}
            onChange={(value) => set('visualFirst', value || options.create3D)}
            label="Visual First"
          />
        </OptionRow>
        <OptionRow label="Create 3D" hint="Generate 3D model from concept">
          <Toggle hideLabel
            checked={options.create3D}
            onChange={(value) => onChange({ ...options, create3D: value, visualFirst: value || options.visualFirst })}
            label="Create 3D"
          />
        </OptionRow>
        <OptionRow label="Review" hint="Code review before applying">
          <Toggle hideLabel checked={options.review} onChange={(v) => set('review', v)} label="Review" />
        </OptionRow>
        <OptionRow label="Auto Test" hint="Run Play Test after build">
          <Toggle hideLabel checked={options.autoTest} onChange={(v) => set('autoTest', v)} label="Auto Test" />
        </OptionRow>
        <OptionRow label="Auto Fix" hint="Automatically fix detected errors">
          <Toggle hideLabel checked={options.autoFix} onChange={(v) => set('autoFix', v)} label="Auto Fix" />
        </OptionRow>
        <OptionRow label="Approval" hint="ASK waits at every write gate. SAFE AUTO skips low-risk code gates after an approved review. FULL AUTO skips local write gates but never bypasses policy blocks.">
          <Select
            value={options.approvalMode}
            options={[
              { id: 'ASK', label: 'ASK' },
              { id: 'SAFE_AUTO', label: 'SAFE AUTO' },
              { id: 'FULL_AUTO', label: 'FULL AUTO' },
            ]}
            onChange={(value) => {
              const mode = value as TaskOptions['approvalMode'];
              onChange({ ...options, approvalMode: mode, approval: mode !== 'FULL_AUTO' });
            }}
          />
        </OptionRow>
        <OptionRow label="Effort" hint="Controls planning depth, context reads, and QA depth">
          <Select
            value={options.effort ?? 'AUTO'}
            options={[
              { id: 'AUTO', label: 'AUTO' },
              { id: 'MIN', label: 'MIN' },
              { id: 'MED', label: 'MED' },
              { id: 'MAX', label: 'MAX' },
            ]}
            onChange={(value) => set('effort', value as TaskOptions['effort'])}
          />
        </OptionRow>
        <OptionRow label="Research" hint="AUTO routes complex tasks through Gemini and the local scout when useful">
          <Select
            value={options.research ?? 'AUTO'}
            options={[
              { id: 'AUTO', label: 'AUTO' },
              { id: 'ON', label: 'ON' },
              { id: 'OFF', label: 'OFF' },
            ]}
            onChange={(value) => set('research', value as TaskOptions['research'])}
          />
        </OptionRow>
        <OptionRow label="Verify" hint="Continue repair and verification cycles until convergence or the hard safety cap">
          <Toggle hideLabel
            checked={options.continuousVerification ?? true}
            onChange={(value) => set('continuousVerification', value)}
            label="Verify"
          />
        </OptionRow>
        <OptionRow label="Risk" hint="Risk tolerance for generated changes">
          <Select
            value={options.risk}
            options={[
              { id: 'low', label: 'LOW' },
              { id: 'medium', label: 'MED' },
              { id: 'high', label: 'HIGH' },
            ]}
            onChange={(v) => set('risk', v as TaskOptions['risk'])}
          />
        </OptionRow>
        <OptionRow label="Revisions" hint="Maximum revision attempts">
          <NumberInput value={options.revisions} onChange={(v) => set('revisions', v)} min={1} max={64} />
        </OptionRow>
        <OptionRow label="Fix Attempts" hint="Maximum auto-fix attempts">
          <NumberInput value={options.fixAttempts} onChange={(v) => set('fixAttempts', v)} min={1} max={64} />
        </OptionRow>
      </div>
    </div>
  );
}

function OptionRow({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <Tooltip content={hint} side="left">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] items-center gap-3 py-2 border-b border-ink-700">
        <span className="text-2xs uppercase tracking-wider text-ink-300">{label}</span>
        <div className="min-w-0 flex justify-end">{children}</div>
      </div>
    </Tooltip>
  );
}

function NumberInput({ value, onChange, min, max }: { value: number; onChange: (v: number) => void; min: number; max: number }) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(e) => onChange(Math.max(min, Math.min(max, parseInt(e.target.value) || min)))}
      className="w-12 h-6 text-2xs text-center text-ink-50 bg-ink-800 border border-ink-600 focus:border-ink-500"
    />
  );
}
