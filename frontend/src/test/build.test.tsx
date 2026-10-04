import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BuildPage } from '@/features/build/BuildPage';
import { useStore } from '@/store';
import type { Job, Review } from '@/types';

const service = vi.hoisted(() => ({ getApi: vi.fn() }));
vi.mock('@/services', () => ({ getApi: service.getApi }));
const initialState = useStore.getState();
const job: Job = {
  id: 'game-task', title: 'Repair inventory', status: 'RUNNING',
  stage: 'WAITING_CHANGE_APPROVAL', createdAt: 1, updatedAt: 2,
};
const review: Review = {
  decision: 'APPROVE', risk: 'LOW', criticalIssues: [], warnings: [], suggestions: [],
  summary: 'Inventory validation completed', reviewer: 'Reviewer', timestamp: 2, files: [], ready: true,
};

beforeEach(() => {
  useStore.setState(initialState, true);
  useStore.setState({
    currentJobId: job.id, jobs: [job],
    changedFiles: [{ id: 'inventory', name: 'InventoryService.luau', status: 'M', additions: 1, deletions: 0, diff: [] }],
  });
});

describe('restored build workspace', () => {
  it('loads the independent review and approves the active task', async () => {
    const approveChanges = vi.fn().mockResolvedValue({ ok: true });
    service.getApi.mockReturnValue({ getReview: vi.fn().mockResolvedValue(review), approveChanges });
    render(<BuildPage />);
    expect(await screen.findByText(review.summary!)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'APPROVE' }));
    await waitFor(() => expect(approveChanges).toHaveBeenCalledWith(job.id));
  });

  it('keeps approval disabled outside the pending change gate', async () => {
    const getReview = vi.fn().mockResolvedValue({ ...review, ready: false });
    service.getApi.mockReturnValue({ getReview });
    useStore.setState({ jobs: [{ ...job, stage: 'BUILDING' }] });
    render(<BuildPage />);
    await waitFor(() => expect(getReview).toHaveBeenCalledWith(job.id));
    expect(screen.queryByText('INDEPENDENT REVIEW')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'APPROVE' })).toBeDisabled();
  });
});
