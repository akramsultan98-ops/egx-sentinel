'use client';

import { useState } from 'react';

import { CompareSlider } from '@/components/fitting-room/CompareSlider';
import { Icon } from '@/components/ui/Icon';
import { Modal } from '@/components/ui/Modal';
import { cn } from '@/lib/cn';
import type { Look } from '@/state/fitting-room-context';

interface LookViewerProps {
  look: Look | null;
  onClose(): void;
  onAddAllToBag(): void;
  onTryAnother(): void;
}

/** Full-size result: single view or before/after wipe, plus download and share. */
export function LookViewer({ look, onClose, onAddAllToBag, onTryAnother }: LookViewerProps) {
  const [mode, setMode] = useState<'result' | 'compare'>('result');
  const [message, setMessage] = useState<string | null>(null);

  if (!look) return null;

  const canCompare = Boolean(look.subjectDataUrl);

  async function download(current: Look) {
    setMessage(null);
    try {
      const response = await fetch(current.imageUrl);
      if (!response.ok) throw new Error();
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `fitting-room-${current.id}.${blob.type.includes('svg') ? 'svg' : 'png'}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setMessage('That result has expired. Generate it again to download.');
    }
  }

  async function share(current: Look) {
    setMessage(null);
    try {
      const response = await fetch(current.imageUrl);
      if (!response.ok) throw new Error();
      const blob = await response.blob();
      const file = new File([blob], `fitting-room-${current.id}.png`, { type: blob.type });

      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: 'My fitting room look' });
        return;
      }
      await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
      setMessage('Copied to your clipboard.');
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      setMessage('Sharing is not available in this browser — download the image instead.');
    }
  }

  return (
    <Modal open onClose={onClose} labelledBy="look-viewer-title" size="wide">
      <div className="grid md:grid-cols-[1.35fr_1fr]">
        <div className="relative bg-ink-900 p-4 sm:p-6">
          {mode === 'compare' && canCompare ? (
            <CompareSlider beforeSrc={look.subjectDataUrl} afterSrc={look.imageUrl} />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- session-scoped API image
            <img
              src={look.imageUrl}
              alt="Your virtual try-on"
              className="mx-auto max-h-[60vh] w-auto rounded-xl"
            />
          )}

          {canCompare ? (
            <div className="mt-4 inline-flex rounded-lg border border-ink-700 p-1">
              {(['result', 'compare'] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMode(option)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-[12px] transition',
                    mode === option ? 'bg-ink-700 text-bone-50' : 'text-bone-500 hover:text-bone-200',
                  )}
                >
                  {option === 'result' ? 'Result' : 'Before / after'}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="border-t border-ink-700/70 p-6 md:border-l md:border-t-0">
          <h2 id="look-viewer-title" className="font-display text-xl font-medium text-bone-50">
            Your look
          </h2>
          <p className="mt-1.5 text-[12px] text-bone-500">
            {new Date(look.createdAt).toLocaleString()} · {look.providerLabel}
          </p>

          {look.simulated ? (
            <p className="mt-4 flex items-start gap-2 rounded-lg border border-accent-700/50 bg-accent-700/10 px-3 py-2.5 text-[11.5px] leading-relaxed text-accent-300">
              <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
              <span>
                <strong className="font-medium">Simulated preview.</strong> The garment artwork is
                overlaid on your photo — no AI model generated this image.
              </span>
            </p>
          ) : null}

          <h3 className="mt-6 text-eyebrow">Pieces in this look</h3>
          <ul className="mt-2.5 space-y-1.5 text-[13px] text-bone-200">
            {look.garmentNames.map((name) => (
              <li key={name} className="flex items-start gap-2">
                <Icon name="check" size={13} className="mt-1 shrink-0 text-accent-600" />
                {name}
              </li>
            ))}
          </ul>

          <div className="mt-7 grid grid-cols-2 gap-2">
            <ActionButton icon="download" onClick={() => void download(look)}>
              Download
            </ActionButton>
            <ActionButton icon="share" onClick={() => void share(look)}>
              Share
            </ActionButton>
            <ActionButton icon="hanger" onClick={onTryAnother}>
              Try another
            </ActionButton>
            <ActionButton icon="bag-plus" onClick={onAddAllToBag} primary>
              Add to bag
            </ActionButton>
          </div>

          {message ? (
            <p role="status" className="mt-3 text-[12px] text-bone-400">
              {message}
            </p>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

function ActionButton({
  children,
  icon,
  onClick,
  primary,
}: {
  children: React.ReactNode;
  icon: 'download' | 'share' | 'hanger' | 'bag-plus';
  onClick(): void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-[12px] font-medium transition',
        primary
          ? 'bg-bone-50 text-ink-900 hover:bg-white'
          : 'border border-ink-600 text-bone-200 hover:border-ink-500 hover:text-bone-50',
      )}
    >
      <Icon name={icon} size={15} />
      {children}
    </button>
  );
}
