'use client';

import { useCallback, useId, useRef, useState } from 'react';

import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import { prepareUpload } from '@/lib/image-client';
import { ACCEPTED_UPLOAD_TYPES, MAX_UPLOAD_BYTES, ValidationError, formatBytes } from '@/lib/try-on/validate';
import { useFittingRoom } from '@/state/fitting-room-context';

const GUIDANCE = [
  'Stand against a plain wall in even, natural light.',
  'Frame yourself head to knee, facing the camera.',
  'Wear fitted clothing so the garment has a clear silhouette.',
  'Keep your arms away from your body and your pose open.',
];

/**
 * Photo intake.
 *
 * Validation and downscaling happen here, in the browser — an invalid file
 * never leaves the device, and a valid one is reduced to a sensible size before
 * it is held in memory. The photo is still not sent anywhere until the shopper
 * presses Generate.
 */
export function PhotoUploader() {
  const { subject, setSubject, useDemoModel } = useFittingRoom();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  const accept = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      setError(null);
      setBusy(true);
      try {
        const prepared = await prepareUpload(file);
        setSubject({
          kind: 'upload',
          dataUrl: prepared.dataUrl,
          width: prepared.width,
          height: prepared.height,
          label: prepared.sourceName,
        });
      } catch (cause) {
        setError(
          cause instanceof ValidationError || cause instanceof Error
            ? cause.message
            : 'That photo could not be read.',
        );
      } finally {
        setBusy(false);
      }
    },
    [setSubject],
  );

  if (subject) {
    return (
      <div className="rounded-xl border border-ink-700 bg-ink-800/60 p-3">
        <div className="flex items-center gap-3">
          <span className="grid size-14 shrink-0 place-items-center overflow-hidden rounded-lg bg-ink-900">
            {subject.kind === 'upload' ? (
              // eslint-disable-next-line @next/next/no-img-element -- in-memory data URL
              <img src={subject.dataUrl} alt="" className="size-full object-cover" />
            ) : (
              <Icon name="user" size={20} className="text-bone-500" />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] text-bone-100">
              {subject.kind === 'upload' ? subject.label : 'Studio figure'}
            </p>
            <p className="mt-0.5 text-[11px] text-bone-600">
              {subject.kind === 'upload'
                ? `${subject.width}×${subject.height} · stays on your device until you generate`
                : 'A stand-in model — upload a photo to see yourself'}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="rounded-md p-2 text-bone-400 transition hover:text-bone-50"
              aria-label="Replace photo"
              title="Replace photo"
            >
              <Icon name="upload" size={15} />
            </button>
            <button
              type="button"
              onClick={() => setSubject(null)}
              className="rounded-md p-2 text-bone-400 transition hover:text-critical"
              aria-label="Remove photo"
              title="Remove photo"
            >
              <Icon name="trash" size={15} />
            </button>
          </div>
        </div>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={ACCEPTED_UPLOAD_TYPES.join(',')}
          className="sr-only"
          onChange={(event) => {
            void accept(event.target.files?.[0]);
            event.target.value = '';
          }}
        />
      </div>
    );
  }

  return (
    <div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void accept(event.dataTransfer.files?.[0]);
        }}
        className={cn(
          'rounded-xl border border-dashed p-5 text-center transition',
          dragging ? 'border-accent-500 bg-accent-500/8' : 'border-ink-600 bg-ink-800/40',
        )}
      >
        <span
          className={cn(
            'mx-auto grid size-11 place-items-center rounded-full transition',
            busy ? 'bg-accent-500/15 text-accent-400' : 'bg-ink-700 text-bone-400',
          )}
        >
          <Icon name={busy ? 'sparkle' : 'upload'} size={19} className={busy ? 'animate-pulse' : undefined} />
        </span>

        <p className="mt-3 text-[13px] font-medium text-bone-100">
          {busy ? 'Reading your photo…' : 'Upload your photo'}
        </p>
        <p className="mt-1 text-[11px] text-bone-600">
          Drag one in, or choose a file · JPEG, PNG or WebP up to {formatBytes(MAX_UPLOAD_BYTES)}
        </p>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-bone-50 px-4 py-2.5 text-[12px] font-medium text-ink-900 transition hover:bg-white disabled:opacity-50"
          >
            <Icon name="upload" size={15} />
            Choose photo
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => cameraRef.current?.click()}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-ink-600 px-4 py-2.5 text-[12px] text-bone-200 transition hover:border-ink-500 disabled:opacity-50 sm:hidden"
          >
            <Icon name="camera" size={15} />
            Take a photo
          </button>
        </div>

        <button
          type="button"
          onClick={useDemoModel}
          className="mt-3 text-[11px] text-bone-500 underline decoration-ink-500 underline-offset-4 transition hover:text-bone-200"
        >
          Or preview on our studio figure
        </button>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_UPLOAD_TYPES.join(',')}
          className="sr-only"
          onChange={(event) => {
            void accept(event.target.files?.[0]);
            event.target.value = '';
          }}
        />
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="user"
          className="sr-only"
          onChange={(event) => {
            void accept(event.target.files?.[0]);
            event.target.value = '';
          }}
        />
      </div>

      {error ? (
        <p
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/10 px-3 py-2.5 text-[12px] text-bone-100"
        >
          <Icon name="alert" size={14} className="mt-0.5 shrink-0 text-critical" />
          {error}
        </p>
      ) : null}

      <details className="group mt-3 rounded-lg border border-ink-700 bg-ink-800/40">
        <summary className="flex cursor-pointer list-none items-center justify-between px-3.5 py-2.5 text-[12px] text-bone-300">
          <span className="inline-flex items-center gap-2">
            <Icon name="info" size={13} className="text-bone-500" />
            How to get the best result
          </span>
          <Icon name="chevron-down" size={14} className="text-bone-600 transition group-open:rotate-180" />
        </summary>
        <ul className="space-y-1.5 border-t border-ink-700 px-3.5 py-3 text-[11.5px] leading-relaxed text-bone-400">
          {GUIDANCE.map((line) => (
            <li key={line} className="flex gap-2">
              <Icon name="check" size={12} className="mt-1 shrink-0 text-accent-600" />
              {line}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
