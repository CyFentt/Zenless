import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi, getSocket } from '@/services';
import { handleEvent } from '@/store/eventHandler';
import { frontendDiagnostics } from '@/services/diagnostics';
import type { BootState } from '@/types';

export function SplashScreen() {
  const setBooted = useStore((s) => s.setBooted);
  const setBootSteps = useStore((s) => s.setBootSteps);
  const setSocketStatus = useStore((s) => s.setSocketStatus);
  const setConnections = useStore((s) => s.setConnections);
  const setAgents = useStore((s) => s.setAgents);
  const setJobs = useStore((s) => s.setJobs);
  const setMessages = useStore((s) => s.setMessages);
  const setContextItems = useStore((s) => s.setContextItems);
  const setChangedFiles = useStore((s) => s.setChangedFiles);
  const setViews = useStore((s) => s.setViews);
  const setModelInfo = useStore((s) => s.setModelInfo);
  const setAssets = useStore((s) => s.setAssets);
  const setStudioState = useStore((s) => s.setStudioState);
  const setStudioTree = useStore((s) => s.setStudioTree);
  const setTestState = useStore((s) => s.setTestState);
  const setSettings = useStore((s) => s.setSettings);
  const setDiagnostics = useStore((s) => s.setDiagnostics);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);

  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let unsubscribeEvent = () => {};
    let unsubscribeStatus = () => {};
    let socket: ReturnType<typeof getSocket> | null = null;
    let bootTimer: ReturnType<typeof setTimeout> | null = null;

    const init = async () => {
      frontendDiagnostics.init();

      // 1. Bootstrap
      try {
        const result = await getApi().bootstrap();
        if (cancelled) return;
        setBootSteps(result.steps);
        setProgress(1);
      } catch (error) {
        frontendDiagnostics.capture(error, 'bootstrap', 'Bootstrap failed');
      }

      // 2. Connect WebSocket
      socket = getSocket();
      unsubscribeEvent = socket.on('event', handleEvent);
      unsubscribeStatus = socket.on('status', (status) => {
        if (!cancelled) setSocketStatus(status);
      });
      socket.connect();
      setProgress(2);

      // 3. Load initial data in parallel
      try {
        const [connections, agents, jobs, settings, diagnostics] = await Promise.all([
          getApi().getConnections(),
          getApi().getAgents(),
          getApi().getJobs(),
          getApi().getSettings(),
          getApi().getDiagnostics(),
        ]);
        if (cancelled) return;
        setConnections(connections);
        setAgents(agents);
        setJobs(jobs);
        setSettings(settings);
        setDiagnostics(diagnostics);
        setProgress(3);

        const runningJob = jobs.find((job) => job.status === 'RUNNING' || job.status === 'PAUSED') ?? null;
        setCurrentJobId(runningJob?.id ?? null);

        const [assets, studioState, studioTree] = await Promise.all([
          getApi().getAssets(),
          getApi().getStudioState(),
          getApi().getStudioTree(),
        ]);
        if (cancelled) return;
        setAssets(assets);
        setStudioState(studioState.state);
        setStudioTree(studioTree);

        if (runningJob) {
          const [messages, context, changes, visual, model, testState] = await Promise.all([
            getApi().getMessages(runningJob.id),
            getApi().getContext(runningJob.id),
            getApi().getChanges(runningJob.id),
            getApi().getVisual(runningJob.id),
            getApi().getModel(runningJob.id),
            getApi().getTestState(runningJob.id),
          ]);
          if (cancelled) return;
          setMessages(messages);
          setContextItems(context);
          setChangedFiles(changes);
          setViews(visual.views);
          useStore.getState().setConcept(visual.concept.version, visual.concept.status, visual.concept.prompt);
          setModelInfo(model);
          setTestState(testState);
        }
        setProgress(4);
      } catch (error) {
        frontendDiagnostics.capture(error, 'init', 'Failed to load initial data');
      }

      // 4. Boot complete — wait for core to be ready
      bootTimer = setTimeout(() => {
        if (!cancelled) {
          setBooted(true);
        }
      }, 600);
    };

    init();
    return () => {
      cancelled = true;
      unsubscribeEvent();
      unsubscribeStatus();
      socket?.disconnect();
      if (bootTimer) clearTimeout(bootTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stages: { stage: string; state: BootState }[] = [
    { stage: 'CORE', state: progress >= 1 ? 'READY' : 'CONNECTING' },
    { stage: 'BROWSER', state: progress >= 2 ? 'READY' : 'OFF' },
    { stage: 'AI', state: progress >= 3 ? 'READY' : 'CONNECTING' },
    { stage: 'STUDIO', state: progress >= 4 ? 'READY' : 'OFF' },
  ];

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-ink-950 animate-fade-in">
      <div className="flex flex-col items-center gap-12">
        {/* Logo */}
        <div className="flex flex-col items-center gap-1">
          <span className="text-lg font-bold tracking-[0.4em] text-ink-0">ZENLESS</span>
          <span className="w-12 h-px bg-ink-600" />
        </div>

        {/* Boot stages */}
        <div className="flex flex-col gap-1.5 w-56">
          {stages.map(({ stage, state }) => (
            <div key={stage} className="flex items-center justify-between">
              <span className={`text-2xs uppercase tracking-widest font-medium ${state === 'READY' ? 'text-ink-0' : state === 'CONNECTING' ? 'text-ink-100' : 'text-ink-400'}`}>
                {stage}
              </span>
              <div className="flex items-center gap-1.5">
                {state === 'CONNECTING' && (
                  <span className="w-3 h-px bg-ink-400 animate-pulse-soft" />
                )}
                <span className={`text-2xs uppercase tracking-wider ${state === 'READY' ? 'text-zen-okBright' : state === 'CONNECTING' ? 'text-zen-warnBright' : 'text-ink-400'}`}>
                  {state}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
