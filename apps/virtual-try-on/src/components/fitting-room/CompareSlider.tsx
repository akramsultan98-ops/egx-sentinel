'use client';

import { useCallback, useRef, useState } from 'react';

import { Icon } from '@/components/ui/Icon';

interface CompareSliderProps {
  beforeSrc: string;
  afterSrc: string;
  beforeLabel?: string;
  afterLabel?: string;
}

/**
 * Before/after wipe.
 *
 * Both images are drawn at full size and the "after" layer is clipped, so the
 * two stay in perfect register regardless of aspect ratio. Driven by pointer
 * events (mouse, touch and pen in one path) and by the arrow keys.
 */
export function CompareSlider({
  beforeSrc,
  afterSrc,
  beforeLabel = 'Your photo',
  afterLabel = 'Try-on',
}: CompareSliderProps) {
  const [position, setPosition] = useState(52);
  const frameRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const moveTo = useCallback((clientX: number) => {
    const frame = frameRef.current;
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const next = ((clientX - rect.left) / rect.width) * 100;
    setPosition(Math.min(100, Math.max(0, next)));
  }, []);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    moveTo(event.clientX);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    moveTo(event.clientX);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 10 : 2;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setPosition((current) => Math.max(0, current - step));
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      setPosition((current) => Math.min(100, current + step));
    }
  };

  return (
    <div
      ref={frameRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className="relative select-none overflow-hidden rounded-xl bg-ink-800 touch-none"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- session-scoped API image, not a static asset */}
      <img src={beforeSrc} alt={beforeLabel} className="block w-full" draggable={false} />

      <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${position}%)` }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- session-scoped API image, not a static asset */}
        <img src={afterSrc} alt={afterLabel} className="block size-full object-cover" draggable={false} />
      </div>

      <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-ink-950/75 px-2.5 py-1 text-[10px] uppercase tracking-[0.12em] text-bone-300 backdrop-blur">
        {beforeLabel}
      </span>
      <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-ink-950/75 px-2.5 py-1 text-[10px] uppercase tracking-[0.12em] text-accent-400 backdrop-blur">
        {afterLabel}
      </span>

      <div
        className="pointer-events-none absolute inset-y-0 w-px bg-bone-50/85"
        style={{ left: `${position}%` }}
      />

      <div
        role="slider"
        tabIndex={0}
        aria-label="Compare your photo with the try-on"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(position)}
        onKeyDown={onKeyDown}
        className="absolute top-1/2 grid size-10 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize place-items-center rounded-full border border-bone-50/30 bg-ink-900/85 text-bone-100 shadow-lg backdrop-blur"
        style={{ left: `${position}%` }}
      >
        <Icon name="compare" size={16} />
      </div>
    </div>
  );
}
