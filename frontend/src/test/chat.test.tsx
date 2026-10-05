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
  it.each([['chatgpt', 'Builder'], ['gemini', 'Research']] as const)('shows %s login failures and routes the login action', async (provider, role) => {
    const loginProvider = vi.fn().mockResolvedValue({ ok: true });
    service.getApi.mockReturnValue({
      sendMessage: vi.fn().mockRejectedValue(new ApiError(409, `${role} requires login.`, 'request-1', 'PROVIDER_LOGIN_REQUIRED', { provider })),
      loginProvider,
      getConnections: vi.fn().mockResolvedValue({ bridge: 'READY', browser: 'READY', chatgpt: 'LOGIN', deepseek: 'LOGIN', gemini: 'LOGIN', hunyuan: 'LOGIN', studio: 'OFF' }),
      getAgents: vi.fn().mockResolvedValue([]),
    });
    render(<ChatPage />);

    fireEvent.change(screen.getByPlaceholderText('Message Rubra'), { target: { value: 'Build a collectible coin system' } });
    fireEvent.click(screen.getByLabelText('Send'));

    expect(await screen.findByText(`${role} requires login.`)).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Message Rubra')).toHaveValue('Build a collectible coin system');
    fireEvent.click(screen.getByRole('button', { name: 'LOGIN' }));
    await waitFor(() => expect(loginProvider).toHaveBeenCalledWith(provider));
  });
});
