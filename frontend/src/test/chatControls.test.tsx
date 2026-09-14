import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '@/components/Sidebar';
import { TaskOptionsPanel } from '@/features/chat/TaskOptionsPanel';
import { DEFAULT_TASK_OPTIONS, type ModelCatalog, type ProviderCapabilities, type ProviderDescriptor, type Settings } from '@/types';
import { useStore } from '@/store';

const service = vi.hoisted(() => ({ getApi: vi.fn() }));

vi.mock('@/services', () => ({ getApi: service.getApi }));

const capabilities: ProviderCapabilities = {
  supportsText: true,
  supportsReasoning: true,
  reasoningLevels: ['AUTO', 'MAXIMUM'],
  supportsSearch: true,
  supportsFiles: false,
  acceptedMimeTypes: [],
  acceptedExtensions: [],
  maxFiles: 0,
  maxBytesPerFile: 0,
  supportsImages: false,
  supportsVision: false,
  supportsAudio: false,
  supportsArchives: false,
  supportsCodeExecution: false,
  supportsTools: false,
  supportsImageGeneration: false,
  supports3DGeneration: false,
  supportsGeometry: false,
  supportsTexture: false,
  supportsDownload: false,
  supportsCancel: true,
  supportsStreaming: true,
  supportsModelSelection: true,
  supportsModeSelection: true,
};

const providers: ProviderDescriptor[] = [{
  providerId: 'deepseek',
  displayName: 'DeepSeek',
  webUrl: 'https://chat.deepseek.com',
  support: 'BETA',
  adapter: 'web',
  roles: ['REVIEWER'],
  modes: [
    { id: 'instant', label: 'Instant', capabilities },
    { id: 'expert', label: 'Expert', capabilities },
  ],
  enabled: true,
  authState: 'READY',
  availabilityState: 'READY',
  route: 'webview2',
  selection: { mode: 'instant' },
  liveCapabilities: capabilities,
}];

const settings: Settings = {
  models: {
    chatgpt: { model: 'auto', reasoning: true },
    deepseek: { model: 'DeepSeek Current', reasoning: true },
    hunyuan: { version: 'auto', quality: 'standard' },
    smartRouting: true,
  },
  autoApprove: false,
  maxRevisions: 3,
  bridgePort: 0,
};

const catalog: ModelCatalog = {
  chatgpt: { models: [] },
  deepseek: {
    models: [{ id: 'DeepSeek Current', label: 'DeepSeek Current', source: 'LIVE' }],
    modes: providers[0].modes,
    selection: { mode: 'instant' },
    liveCapabilities: capabilities,
  },
  hunyuan: { versions: [], qualities: [] },
};

const initialState = useStore.getState();

beforeEach(() => {
  useStore.setState(initialState, true);
  useStore.setState({
    providers,
    settings,
    connections: { ...initialState.connections, deepseek: 'READY' },
  });
});

describe('Chat-first controls', () => {
  it('keeps primary navigation compact and exposes Logs separately', () => {
    render(<Sidebar />);

    expect(screen.queryByLabelText('HOME')).toBeNull();
    expect(screen.queryByLabelText('SETTINGS')).toBeNull();
    expect(screen.getByLabelText('CHAT')).toBeInTheDocument();
    expect(screen.getByLabelText('LOGS')).toBeInTheDocument();
  });

  it('shows live models, verified modes, and text fallback in Chat controls', async () => {
    const selectProvider = vi.fn().mockResolvedValue({ ...providers[0], selection: { mode: 'expert' } });
    service.getApi.mockReturnValue({
      getSettings: vi.fn().mockResolvedValue(settings),
      getProviders: vi.fn().mockResolvedValue(providers),
      getModels: vi.fn().mockResolvedValue(catalog),
      selectProvider,
    });
    render(<TaskOptionsPanel options={DEFAULT_TASK_OPTIONS} onChange={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Providers' }));

    const card = (await screen.findByText('DeepSeek')).closest('section');
    expect(card).not.toBeNull();
    const providerCard = within(card!);
    expect(providerCard.getByText('Reviewer')).toBeInTheDocument();
    expect(providerCard.getByText('DeepSeek Current')).toBeInTheDocument();
    expect(providerCard.getByText('Text fallback')).toBeInTheDocument();
    fireEvent.click(providerCard.getByRole('button', { name: /Instant/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Expert' }));

    await waitFor(() => expect(selectProvider).toHaveBeenCalledWith('deepseek', { mode: 'expert' }));
  });
});
