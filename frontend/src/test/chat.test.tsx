import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '@/features/chat/ChatPage';
import { ApiError } from '@/services/api/realApi';
import { useStore } from '@/store';

const service = vi.hoisted(() => ({ getApi: vi.fn() }));

vi.mock('@/services', () => ({ getApi: service.getApi }));

const initialState = useStore.getState();

beforeEach(() => useStore.setState(initialState, true));

describe('ChatPage', () => {
  it('shows a login response instead of remaining silent', async () => {
    const loginProvider = vi.fn().mockResolvedValue({ ok: true });
    service.getApi.mockReturnValue({
      sendMessage: vi.fn().mockRejectedValue(new ApiError(409, 'ChatGPT requires login.', 'request-1', 'PROVIDER_LOGIN_REQUIRED', { provider: 'chatgpt' })),
      loginProvider,
      getConnections: vi.fn().mockResolvedValue({ bridge: 'READY', browser: 'READY', chatgpt: 'LOGIN', deepseek: 'LOGIN', hunyuan: 'LOGIN', studio: 'OFF' }),
      getAgents: vi.fn().mockResolvedValue([]),
    });
    render(<ChatPage />);

    fireEvent.change(screen.getByPlaceholderText('Message Zenless'), { target: { value: 'Build a collectible coin system' } });
    fireEvent.click(screen.getByLabelText('Send'));

    expect(await screen.findByText('ChatGPT requires login.')).toBeInTheDocument();
    expect(screen.getByText('Build a collectible coin system')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'LOGIN' }));
    await waitFor(() => expect(loginProvider).toHaveBeenCalledWith('chatgpt'));
  });
});
