import { create } from 'zustand';

type Notice = { id: string; title: string; kind: 'success' | 'error' | 'info' };
export const useNotices = create<{ items: Notice[]; remove: (id: string) => void }>((set) => ({
  items: [], remove: (id) => set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
}));
export function notify(title: string, kind: Notice['kind'] = 'info') {
  const items = useNotices.getState().items;
  if (items.some((item) => item.title === title)) return;
  useNotices.setState({ items: [...items, { id: `${Date.now()}-${Math.random()}`, title, kind }].slice(-3) });
}
