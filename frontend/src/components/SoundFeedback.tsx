import { useEffect, useState } from 'react';
import { Volume2, VolumeX } from 'lucide-react';

export function SoundFeedback() {
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    if (!enabled) return;
    let audio: HTMLAudioElement | null = null;
    const activate = (event: MouseEvent) => {
      if (!event.isTrusted || document.hidden || !(event.target instanceof Element)) return;
      const button = event.target.closest('button');
      if (!button || button.disabled || button.dataset.sound === 'none') return;
      const label = `${button.getAttribute('aria-label') ?? ''} ${button.textContent ?? ''}`.toLowerCase();
      const sound = button.closest('[aria-label="Workspaces"]') ? 'select'
        : /send|submit/.test(label) ? 'send'
        : /close|back|cancel/.test(label) ? 'back' : 'click';
      audio ??= new Audio();
      audio.volume = 0.35;
      audio.pause();
      audio.src = `/sounds/${sound}.wav`;
      void audio.play().catch(() => setEnabled(false));
    };
    document.addEventListener('click', activate);
    return () => {
      document.removeEventListener('click', activate);
      audio?.pause();
      audio?.removeAttribute('src');
    };
  }, [enabled]);
  const Icon = enabled ? Volume2 : VolumeX;
  return (
    <button className="zen-icon-button" aria-label={enabled ? 'Mute interface sounds' : 'Enable interface sounds'}
      aria-pressed={enabled} data-sound="none" onClick={() => setEnabled(!enabled)}>
      <Icon size={12} />
    </button>
  );
}
