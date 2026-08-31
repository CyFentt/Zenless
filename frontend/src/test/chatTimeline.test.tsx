import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useStore } from '@/store';
import { TopBar } from '@/components/TopBar';
import { ChatPage } from '@/features/chat/ChatPage';

const initialState = useStore.getState();

beforeEach(() => {
  useStore.setState(initialState, true);
});

describe('TopBar Project Identity & Provider Role', () => {
  it('displays NO PROJECT when Studio is offline and does not hardcode ARENA', () => {
    useStore.setState({ studioState: 'OFFLINE', studioTree: [] });
    render(<TopBar />);
    expect(screen.getByText('NO PROJECT')).toBeInTheDocument();
    expect(screen.queryByText('ARENA')).toBeNull();
  });

  it('displays real project name from Studio tree when online', () => {
    useStore.setState({
      studioState: 'ONLINE',
      studioTree: [{ id: '1', name: 'SciFi_Game', className: 'DataModel', path: 'Game' }],
    });
    render(<TopBar />);
    expect(screen.getByText('SCIFI_GAME')).toBeInTheDocument();
    expect(screen.queryByText('ARENA')).toBeNull();
  });

  it('separates provider identity from role in status bar', () => {
    useStore.setState({
      agents: [{ id: 'chatgpt', name: 'ChatGPT', status: 'READY' }],
    });
    render(<TopBar />);
    expect(screen.getByText('ChatGPT · Builder')).toBeInTheDocument();
  });
});

describe('ChatTimeline Artifact & Activity Rendering', () => {
  it('renders ChatActivity events in timeline', () => {
    useStore.setState({
      currentJobId: 'job_001',
      activities: [
        {
          id: 'act_1',
          jobId: 'job_001',
          phase: 'BUILD',
          status: 'RUNNING',
          title: 'Updating BombService.luau',
          timestamp: Date.now(),
        },
      ],
    });

    render(<ChatPage />);
    expect(screen.getByText('BUILD')).toBeInTheDocument();
    expect(screen.getByText('Updating BombService.luau')).toBeInTheDocument();
  });

  it('renders ChatArtifact code changes card and handles deep link', () => {
    useStore.setState({
      currentJobId: 'job_001',
      artifacts: [
        {
          id: 'art_diff',
          jobId: 'job_001',
          type: 'DIFF',
          name: 'CODE CHANGES READY',
          state: 'READY',
          createdAt: Date.now(),
          metadata: { risk: 'LOW', fileCount: 2, reviewer: 'DeepSeek', decision: 'APPROVE' },
        },
      ],
    });

    render(<ChatPage />);
    expect(screen.getByText('CODE CHANGES READY')).toBeInTheDocument();
    expect(screen.getAllByText('APPROVE').length).toBeGreaterThan(0);

    const diffButton = screen.getByText('VIEW FULL DIFF');
    fireEvent.click(diffButton);
    expect(useStore.getState().activePage).toBe('build');
    expect(useStore.getState().currentJobId).toBe('job_001');
  });

  it('renders 6-view image gallery artifact and navigates to visual workspace', () => {
    useStore.setState({
      currentJobId: 'job_001',
      conceptVersion: 1,
      views: [
        { name: 'FRONT', state: 'READY', imageUrl: 'http://localhost/front.png' },
        { name: 'BACK', state: 'READY', imageUrl: 'http://localhost/back.png' },
      ],
    });

    render(<ChatPage />);
    expect(screen.getByText((content) => content.includes('CONCEPT VISUAL'))).toBeInTheDocument();

    const visualButton = screen.getByText('OPEN VISUAL WORKSPACE');
    fireEvent.click(visualButton);
    expect(useStore.getState().activePage).toBe('visual');
  });

  it('renders test results card and navigates to test page', () => {
    useStore.setState({
      currentJobId: 'job_001',
      testCases: [
        { id: 'c1', name: 'spawns player', status: 'PASSED' },
        { id: 'c2', name: 'detonates bomb', status: 'FAILED' },
      ],
      testFailures: [{ id: 'f1', message: 'Bomb clip collision failure', timestamp: Date.now() }],
    });

    render(<ChatPage />);
    expect(screen.getByText('PLAY TEST RESULTS')).toBeInTheDocument();
    expect(screen.getByText('PRIMARY FAILURE:')).toBeInTheDocument();

    const testButton = screen.getByText('VIEW TEST DETAILS');
    fireEvent.click(testButton);
    expect(useStore.getState().activePage).toBe('test');
  });

  it('renders ChatTestCard truthfully without fake 12 counts or fake PASS', () => {
    useStore.setState({
      currentJobId: 'job_001',
      testCases: [
        { id: 'c1', name: 'test 1', status: 'SKIPPED' },
        { id: 'c2', name: 'test 2', status: 'SKIPPED' },
      ],
      testFailures: [],
    });

    render(<ChatPage />);
    expect(screen.getAllByText('SKIPPED').length).toBeGreaterThan(0);
    expect(screen.queryByText('12')).toBeNull();
    expect(screen.queryByText('All automated QA scenarios completed successfully.')).toBeNull();
  });

  it('renders ChatChangeCard truthfully without hardcoded reviewer/risk fallbacks', () => {
    useStore.setState({
      currentJobId: 'job_001',
      artifacts: [
        {
          id: 'art_diff_empty',
          jobId: 'job_001',
          type: 'DIFF',
          name: 'CODE CHANGES PENDING',
          state: 'READY',
          createdAt: Date.now(),
          metadata: {},
        },
      ],
    });

    render(<ChatPage />);
    expect(screen.getByText('CODE CHANGES PENDING')).toBeInTheDocument();
    expect(screen.getByText('PENDING')).toBeInTheDocument();
    expect(screen.getByText('UNASSESSED')).toBeInTheDocument();
    expect(screen.queryByText('DeepSeek')).toBeNull();
  });
});
