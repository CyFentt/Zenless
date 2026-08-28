import { PIPELINE_STEPS, STAGE_LABELS, type PipelineStage } from '@/types';
import { Tooltip } from './Tooltip';

interface PipelineProps {
  stage: PipelineStage;
}

const stageToStep: Record<PipelineStage, number> = {
  NEW: 0,
  COLLECTING_CONTEXT: 0,
  PLANNING: 1,
  GENERATING_CONCEPT: 1,
  WAITING_IMAGE_APPROVAL: 1,
  GENERATING_3D: 1,
  WAITING_3D_APPROVAL: 1,
  BUILDING: 2,
  REVIEWING: 3,
  REVISING: 3,
  WAITING_CHANGE_APPROVAL: 3,
  APPLYING: 4,
  TESTING: 5,
  FIXING: 5,
  FINAL_REVIEW: 5,
  COMPLETE: 6,
  PAUSED: -1,
  BLOCKED: -1,
  FAILED: -1,
};

export function Pipeline({ stage }: PipelineProps) {
  const currentStep = stageToStep[stage];
  const isPaused = stage === 'PAUSED';
  const isBlocked = stage === 'BLOCKED';
  const isFailed = stage === 'FAILED';

  return (
    <div className="flex items-center gap-0">
      {PIPELINE_STEPS.map((step, idx) => {
        const isDone = currentStep > idx || currentStep === 6;
        const isActive = currentStep === idx;

        const color = isFailed
          ? 'text-zen-errBright border-zen-err'
          : isBlocked
            ? 'text-zen-errBright border-zen-err'
            : isPaused && isActive
              ? 'text-zen-warnBright border-zen-warn'
              : isDone
                ? 'text-ink-0 border-ink-300'
                : isActive
                  ? 'text-ink-0 border-ink-0'
                  : 'text-ink-400 border-ink-600';

        return (
          <div key={step} className="flex items-center">
            <Tooltip content={isDone ? `${step} — DONE` : isActive ? `${STAGE_LABELS[stage]}` : step}>
              <div className={`flex items-center gap-1.5 px-2 h-6 border-b ${color} transition-colors duration-150`}>
                <span className={`w-1 h-1 ${isDone ? 'bg-ink-0' : isActive ? 'bg-ink-0 animate-pulse-soft' : 'bg-ink-500'}`} />
                <span className="text-2xs font-medium uppercase tracking-wider">{step}</span>
              </div>
            </Tooltip>
            {idx < PIPELINE_STEPS.length - 1 && (
              <div className={`w-3 h-px ${isDone ? 'bg-ink-300' : 'bg-ink-600'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
