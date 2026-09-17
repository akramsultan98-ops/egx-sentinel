'use client';

import { useCallback, useEffect, useRef } from 'react';

import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  open: boolean;
  onClose(): void;
  children: React.ReactNode;
  labelledBy?: string;
  size?: 'default' | 'wide';
  /** Renders flush to the bottom edge on small screens, like a native sheet. */
  sheetOnMobile?: boolean;
}

/**
 * Accessible dialog: focus is moved in on open, trapped while open, and
 * returned to the trigger on close. Escape and backdrop clicks both dismiss.
 */
export function Modal({
  open,
  onClose,
  children,
  labelledBy,
  size = 'default',
  sheetOnMobile = true,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;

      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;

    restoreRef.current = document.activeElement as HTMLElement | null;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeyDown, true);

    const target = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    target?.focus();

    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.body.style.overflow = overflow;
      restoreRef.current?.focus();
    };
  }, [open, onKeyDown]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 animate-fade cursor-default bg-ink-950/80 backdrop-blur-sm"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={cn(
          'relative z-10 max-h-[92vh] w-full animate-sheet overflow-hidden border border-ink-700 bg-ink-850 shadow-2xl shadow-ink-950/60',
          sheetOnMobile ? 'rounded-t-panel sm:rounded-panel' : 'rounded-panel',
          size === 'wide' ? 'sm:max-w-4xl' : 'sm:max-w-md',
        )}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 z-20 grid size-8 place-items-center rounded-full bg-ink-900/70 text-bone-400 backdrop-blur transition hover:text-bone-50"
        >
          <Icon name="close" size={16} />
        </button>
        {children}
      </div>
    </div>
  );
}
