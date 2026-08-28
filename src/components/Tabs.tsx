import { useState, type ReactNode } from 'react';

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

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2"
      role="switch"
      aria-checked={checked}
      aria-label={label}
    >
      <span className={`relative w-8 h-4 border transition-colors duration-150 ${checked ? 'bg-ink-600 border-ink-500' : 'bg-ink-800 border-ink-600'}`}>
        <span className={`absolute top-0.5 w-2.5 h-2.5 transition-transform duration-150 ${checked ? 'left-4 bg-ink-0' : 'left-0.5 bg-ink-300'}`} />
      </span>
      {label && <span className="text-xs text-ink-100">{label}</span>}
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
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.id === value);
  return (
    <div className="relative">
      {label && <span className="block text-2xs text-ink-300 uppercase tracking-wider mb-1">{label}</span>}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full h-7 px-2 text-xs text-ink-50 bg-ink-800 border border-ink-600 hover:border-ink-500 transition-colors"
      >
        <span>{current?.label ?? value}</span>
        <span className="text-ink-300 text-2xs">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-1 w-full bg-ink-800 border border-ink-600 max-h-40 overflow-y-auto scrollbar-zen">
            {options.map((opt) => (
              <button
                key={opt.id}
                onClick={() => { onChange(opt.id); setOpen(false); }}
                className={`block w-full text-left px-2 h-7 text-xs hover:bg-ink-700 transition-colors ${opt.id === value ? 'text-ink-0' : 'text-ink-100'}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
