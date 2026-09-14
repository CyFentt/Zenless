import { useStore } from '@/store';

export function SplashScreen() {
  const bootSteps = useStore((state) => state.bootSteps);
  const bootError = useStore((state) => state.bootError);

  const complete = bootSteps.filter((step) => step.state === 'READY').length;
  const active = bootSteps.find((step) => step.state === 'CONNECTING') ?? bootSteps.find((step) => step.state !== 'READY');
  return (
    <div className="relative flex h-screen items-center justify-center overflow-hidden bg-ink-950 animate-fade-in">
      <div className="absolute inset-0 loading-grid opacity-70" />
      <div className="relative flex w-72 flex-col items-center">
        <div className="relative mb-10 flex h-28 w-28 items-center justify-center">
          <span className="absolute inset-0 border border-ink-700 animate-loader-frame" />
          <span className="absolute inset-3 border border-ink-500 animate-loader-frame-reverse" />
          <span className="absolute h-px w-36 bg-gradient-to-r from-transparent via-ink-300 to-transparent animate-scan" />
          <span className="text-xl font-semibold tracking-[0.28em] text-ink-0 translate-x-[0.14em]">Z</span>
        </div>
        <div className="text-center">
          <h1 className="text-base font-semibold tracking-[0.42em] text-ink-0 translate-x-[0.21em]">ZENLESS</h1>
          <p className="mt-2 text-[9px] uppercase tracking-[0.24em] text-ink-300">Local development workspace</p>
        </div>
        <div className="mt-10 w-full">
          <div className="flex items-center justify-between text-[9px] uppercase tracking-[0.2em] text-ink-300">
            <span>{active?.stage ?? (bootSteps.length ? 'Finalizing' : 'Waiting for core')}</span>
            <span>{complete}/{bootSteps.length || '—'}</span>
          </div>
          <div className="relative mt-2 h-px overflow-hidden bg-ink-700">
            <span className="absolute inset-y-0 left-0 bg-ink-0 transition-[width] duration-500 ease-out" style={{ width: bootSteps.length ? `${(complete / bootSteps.length) * 100}%` : '12%' }} />
            {!bootSteps.length && <span className="absolute inset-y-0 w-1/3 bg-ink-100 animate-loading-bar" />}
          </div>
          <div className="mt-3 grid grid-cols-5 gap-1">
            {bootSteps.map(({ stage, state }) => <span key={stage} title={`${stage}: ${state}`} className={`h-0.5 transition-colors duration-300 ${state === 'READY' ? 'bg-ink-0' : state === 'CONNECTING' ? 'bg-ink-200 animate-pulse-soft' : 'bg-ink-700'}`} />)}
          </div>
        </div>
        {bootError && <p role="alert" className="mt-6 max-w-xs border border-ink-500 bg-ink-900 px-3 py-2 text-center text-2xs leading-relaxed text-ink-25">{bootError}</p>}
      </div>
    </div>
  );
}
