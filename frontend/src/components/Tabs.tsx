import type { ReactNode } from 'react';

export interface TabItem {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  right?: ReactNode;
}

export function Tabs({ tabs, active, onChange, right }: TabsProps) {
  return (
    <div className="flex items-center justify-between border-b border-ink-600 h-9 px-2">
      <div className="flex items-center gap-0.5 h-full">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`px-3 h-7 text-xs font-medium uppercase tracking-wider transition-colors duration-150 ${
              active === tab.id
                ? 'text-ink-0 border-b border-ink-0 -mb-px'
                : 'text-ink-300 hover:text-ink-100 border-b border-transparent'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export interface SegmentedProps {
  options: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}

export function Segmented({ options, active, onChange }: SegmentedProps) {
  return (
    <div className="inline-flex border border-ink-600">
      {options.map((opt) => (
        <button
          key={opt.id}
          onClick={() => onChange(opt.id)}
          className={`px-2.5 h-6 text-2xs font-medium uppercase tracking-wider transition-colors duration-150 ${
            active === opt.id ? 'bg-ink-600 text-ink-0' : 'text-ink-300 hover:text-ink-100'
          } ${options.indexOf(opt) > 0 ? 'border-l border-ink-600' : ''}`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, hideLabel = false }: { checked: boolean; onChange: (v: boolean) => void; label?: string; hideLabel?: boolean }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="inline-flex shrink-0 items-center gap-2 min-h-8"
      role="switch"
      aria-checked={checked}
      aria-label={label}
    >
      <span className={`relative w-8 h-4 border transition-colors duration-150 ${checked ? 'bg-ink-600 border-ink-500' : 'bg-ink-800 border-ink-600'}`}>
        <span className={`absolute top-0.5 w-2.5 h-2.5 transition-transform duration-150 ${checked ? 'left-4 bg-ink-0' : 'left-0.5 bg-ink-300'}`} />
      </span>
      {label && !hideLabel && <span className="text-xs text-ink-100">{label}</span>}
    </button>
  );
}

interface SelectProps {
  value: string;
  options: { id: string; label: string }[];
  onChange: (v: string) => void;
  label?: string;
}

export function Select({ value, options, onChange, label }: SelectProps) {
  return (
    <label className="block w-full min-w-0">
      {label && <span className="block text-xs text-ink-300 mb-1">{label}</span>}
      <select aria-label={label || 'Model or setting'} value={value} onChange={(event) => onChange(event.target.value)}
        className="w-full h-8 px-2 text-xs text-ink-50 bg-ink-800 border border-ink-500 focus:border-zen-red">
        {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
      </select>
    </label>
  );
}
