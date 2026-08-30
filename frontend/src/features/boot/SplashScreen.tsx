import { useStore } from '@/store';

export function SplashScreen() {
  const bootSteps = useStore((state) => state.bootSteps);
  const bootError = useStore((state) => state.bootError);

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-ink-950 animate-fade-in">
      <div className="flex flex-col items-center gap-12">
        <div className="flex flex-col items-center gap-1">
          <span className="text-lg font-bold tracking-[0.4em] text-ink-0">ZENLESS</span>
          <span className="w-12 h-px bg-ink-600" />
        </div>
        <div className="flex flex-col gap-1.5 w-56">
          {bootSteps.length === 0 && <span className="text-2xs uppercase tracking-wider text-ink-300">WAITING FOR CORE STATE</span>}
          {bootSteps.map(({ stage, state }) => (
            <div key={stage} className="flex items-center justify-between">
              <span className={`text-2xs uppercase tracking-widest font-medium ${state === 'READY' ? 'text-ink-0' : state === 'CONNECTING' ? 'text-ink-100' : 'text-ink-400'}`}>
                {stage}
              </span>
              <div className="flex items-center gap-1.5">
                {state === 'CONNECTING' && <span className="w-3 h-px bg-ink-400 animate-pulse-soft" />}
                <span className={`text-2xs uppercase tracking-wider ${state === 'READY' ? 'text-zen-okBright' : state === 'CONNECTING' ? 'text-zen-warnBright' : 'text-ink-400'}`}>
                  {state}
                </span>
              </div>
            </div>
          ))}
        </div>
        {bootError && <p role="alert" className="max-w-xs text-center text-2xs text-zen-warnBright">{bootError}</p>}
      </div>
    </div>
  );
}
