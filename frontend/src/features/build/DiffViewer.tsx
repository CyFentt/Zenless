import { useState } from 'react';
import type { ChangedFile } from '@/types';

interface DiffViewerProps {
  file: ChangedFile;
  onSaveContent?: (fileId: string, newContent: string) => Promise<void>;
}

export function DiffViewer({ file, onSaveContent }: DiffViewerProps) {
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const handleStartEdit = () => {
    const content = file.diff
      .filter((line) => line.type === 'unchanged' || line.type === 'added')
      .map((line) => line.content)
      .join('\n');
    setEditContent(content);
    setEditing(true);
  };

  const handleSave = async () => {
    if (!onSaveContent) return;
    setSaving(true);
    setSaveError('');
    try {
      await onSaveContent(file.id, editContent);
      setEditing(false);
    } catch (error) {
      setSaveError(error instanceof Error && error.message ? error.message : 'The change could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-ink-950 border border-ink-700 rounded overflow-hidden">
      <div className="flex items-center justify-between px-4 h-9 bg-ink-900 border-b border-ink-700">
        <div className="flex items-center gap-3 font-mono text-xs">
          <span className="font-semibold text-ink-100">{file.name}</span>
          <span
            className={`px-1.5 py-0.5 rounded text-2xs font-semibold ${
              file.status === 'A'
                ? 'bg-zen-ok/20 text-zen-okBright'
                : file.status === 'D'
                  ? 'bg-zen-err/20 text-zen-errBright'
                  : 'bg-ink-700 text-ink-200'
            }`}
          >
            {file.status === 'A' ? 'ADDED' : file.status === 'D' ? 'DELETED' : 'MODIFIED'}
          </span>
          <span className="text-zen-okBright">+{file.additions}</span>
          <span className="text-zen-errBright">-{file.deletions}</span>
        </div>

        <div className="flex items-center gap-2">
          {editing ? (
            <>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-2 py-1 text-2xs font-mono bg-zen-ok text-black rounded font-medium hover:bg-zen-okBright transition-colors disabled:opacity-50"
              >
                {saving ? 'SAVING...' : 'SAVE'}
              </button>
              <button
                onClick={() => setEditing(false)}
                disabled={saving}
                className="px-2 py-1 text-2xs font-mono bg-ink-700 text-ink-200 rounded hover:text-ink-0 transition-colors"
              >
                CANCEL
              </button>
            </>
          ) : (
            onSaveContent && (
              <button
                onClick={handleStartEdit}
                className="px-2 py-1 text-2xs font-mono bg-ink-800 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-700 transition-colors"
              >
                EDIT
              </button>
            )
          )}
        </div>
      </div>

      {saveError && (
        <div role="alert" className="px-3 py-2 text-2xs text-zen-errBright border-b border-zen-err/30 bg-zen-err/10">
          {saveError}
        </div>
      )}
      {editing ? (
        <div className="flex-1 p-2 bg-ink-950">
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="w-full h-full bg-ink-900 text-ink-100 font-mono text-xs p-3 border border-ink-700 rounded focus:outline-none focus:border-ink-500 resize-none"
            spellCheck={false}
          />
        </div>
      ) : (
        <div className="flex-1 overflow-auto font-mono text-xs scrollbar-zen select-text">
          {file.diff.length === 0 ? (
            <div className="p-4 text-ink-400 italic">No diff content available.</div>
          ) : (
            <table className="w-full border-collapse">
              <tbody>
                {file.diff.map((line, idx) => {
                  let bgColor = '';
                  let textColor = 'text-ink-200';
                  let symbol = ' ';

                  if (line.type === 'added') {
                    bgColor = 'bg-zen-ok/10';
                    textColor = 'text-zen-okBright';
                    symbol = '+';
                  } else if (line.type === 'removed') {
                    bgColor = 'bg-zen-err/10';
                    textColor = 'text-zen-errBright';
                    symbol = '-';
                  } else if (line.type === 'hunk') {
                    bgColor = 'bg-ink-850';
                    textColor = 'text-ink-400 font-semibold';
                    symbol = '@';
                  }

                  return (
                    <tr key={idx} className={`${bgColor} hover:bg-ink-850/50 transition-colors`}>
                      <td className="w-10 px-2 py-0.5 text-right text-ink-400 select-none border-r border-ink-800/50">
                        {line.oldLine ?? ''}
                      </td>
                      <td className="w-10 px-2 py-0.5 text-right text-ink-400 select-none border-r border-ink-800">
                        {line.newLine ?? ''}
                      </td>
                      <td className="w-6 px-1 py-0.5 text-center select-none font-bold">
                        <span className={textColor}>{symbol}</span>
                      </td>
                      <td className={`px-2 py-0.5 whitespace-pre ${textColor}`}>
                        {line.content}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
