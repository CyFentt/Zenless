import { useStore } from '@/store';
import { getApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import type { ChangedFile } from '@/types';
import { Pencil, Check, X } from 'lucide-react';
import { useState } from 'react';

interface Props {
  file: ChangedFile;
}

export function DiffViewer({ file }: Props) {
  const currentJobId = useStore((s) => s.currentJobId);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');

  const handleEdit = () => {
    const content = file.diff.map((l) => l.content).join('\n');
    setEditContent(content);
    setEditing(true);
  };

  const handleApplyEdit = async () => {
    if (!currentJobId) return;
    try { await getApi().editChanges(currentJobId, file.id, editContent); setEditing(false); } catch (error) { frontendDiagnostics.capture(error, 'diff', 'Failed to save edit'); }
  };

  const handleReject = async () => {
    if (!currentJobId) return;
    try { await getApi().rejectChanges(currentJobId); } catch (error) { frontendDiagnostics.capture(error, 'diff', 'Failed to reject changes'); }
  };

  const handleApply = async () => {
    if (!currentJobId) return;
    try { await getApi().approveChanges(currentJobId); } catch (error) { frontendDiagnostics.capture(error, 'diff', 'Failed to apply changes'); }
  };

  if (editing) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between px-3 h-8 border-b border-ink-600 shrink-0">
          <span className="text-2xs uppercase tracking-wider text-ink-100">{file.name} — EDIT</span>
          <div className="flex gap-1">
            <button onClick={handleApplyEdit} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800"><Check size={10} />SAVE</button>
            <button onClick={() => setEditing(false)} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-ink-300 border border-ink-600 hover:bg-ink-800"><X size={10} />CANCEL</button>
          </div>
        </div>
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          className="flex-1 w-full bg-ink-950 text-2xs font-mono text-ink-50 p-3 resize-none border-none focus:outline-none scrollbar-zen"
          spellCheck={false}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* File header */}
      <div className="flex items-center justify-between px-3 h-8 border-b border-ink-600 shrink-0">
        <div className="flex items-center gap-2">
          <span className={`text-2xs font-mono ${file.status === 'A' ? 'text-zen-okBright' : file.status === 'D' ? 'text-zen-errBright' : 'text-zen-warnBright'}`}>{file.status}</span>
          <span className="text-2xs uppercase tracking-wider text-ink-100">{file.name}</span>
          <span className="text-2xs text-zen-okBright font-mono">+{file.additions}</span>
          <span className="text-2xs text-zen-errBright font-mono">-{file.deletions}</span>
        </div>
        <div className="flex gap-1">
          <button onClick={handleReject} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-zen-errBright border border-ink-600 hover:bg-ink-800 transition-colors">REJECT</button>
          <button onClick={handleEdit} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800 transition-colors"><Pencil size={10} />EDIT</button>
          <button onClick={handleApply} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800 transition-colors">APPLY</button>
        </div>
      </div>

      {/* Diff content */}
      <div className="flex-1 overflow-auto scrollbar-zen bg-ink-950">
        <pre className="text-2xs font-mono leading-relaxed">
          {file.diff.map((line, idx) => {
            const bg = line.type === 'added' ? 'bg-zen-ok/10' : line.type === 'removed' ? 'bg-zen-err/10' : '';
            const color = line.type === 'added' ? 'text-zen-okBright' : line.type === 'removed' ? 'text-zen-errBright' : 'text-ink-150';
            const prefix = line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' ';
            const lineNum = line.newLine ?? line.oldLine ?? '';
            return (
              <div key={idx} className={`flex ${bg}`}>
                <span className="text-ink-500 select-none w-8 text-right pr-2 shrink-0">{line.oldLine ?? ''}</span>
                <span className="text-ink-500 select-none w-8 text-right pr-2 shrink-0 border-r border-ink-700">{lineNum}</span>
                <span className={`pl-2 pr-2 ${color}`}>
                  <span className="select-none">{prefix} </span>
                  {line.content || ' '}
                </span>
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
