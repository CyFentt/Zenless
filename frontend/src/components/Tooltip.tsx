import type { ReactNode } from 'react';
import * as Primitive from '@radix-ui/react-tooltip';

interface TooltipProps {
  content: string;
  children: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
}

export function Tooltip({ content, children, side = 'right' }: TooltipProps) {
  return (
    <Primitive.Provider delayDuration={400} skipDelayDuration={150}>
      <Primitive.Root>
        <Primitive.Trigger asChild>{children}</Primitive.Trigger>
        <Primitive.Portal>
          <Primitive.Content side={side} sideOffset={8} collisionPadding={12}
            className="z-[100] max-w-xs px-3 py-2 text-xs leading-relaxed text-ink-50 bg-ink-800 border border-ink-500 shadow-xl animate-fade-in">
            {content}
          </Primitive.Content>
        </Primitive.Portal>
      </Primitive.Root>
    </Primitive.Provider>
  );
}
