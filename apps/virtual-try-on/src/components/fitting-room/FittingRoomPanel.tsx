'use client';

import { useEffect, useState } from 'react';

import { LookViewer } from '@/components/fitting-room/LookViewer';
import { PhotoUploader } from '@/components/fitting-room/PhotoUploader';
import { Icon } from '@/components/ui/Icon';
import { DEFAULT_MODEL_IMAGE } from '@/data/catalog';
import { cn } from '@/lib/cn';
import { useFittingRoom } from '@/state/fitting-room-context';
import { useStore } from '@/state/store-context';

/**
 * The fitting room.
 *
 * A floating panel on desktop and a bottom sheet on mobile, holding the whole
 * flow: pick pieces, add a photo, generate, compare, buy. It is the only place
 * in the app that can start a generation, and it never does so without a click.
 */
export function FittingRoomPanel() {
  const {
    open,
    setOpen,
    picks,
    removePick,
    subject,
    job,
    looks,
    activeLook,
    setActiveLook,
    provider,
    consented,
    grantConsent,
    stage,
    error,
    dismissError,
    generate,
    cancel,
    startOver,
  } = useFittingRoom();

  const { addToBag } = useStore();
  const [expanded, setExpanded] = useState(false);
  const [showConsent, setShowConsent] = useState(false);

  // Opening the panel should not steal the page scroll on desktop, but a
  // bottom sheet covering the viewport must lock it.
  useEffect(() => {
    if (!open) return;
    const mobile = window.matchMedia('(max-width: 1023px)').matches;
    if (!mobile) return;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = overflow;
    };
  }, [open]);

  if (!open) {
    return <LauncherButton count={picks.length} onClick={() => setOpen(true)} />;
  }

  const generating = stage === 'generating';
  const canGenerate = picks.length > 0 && Boolean(subject) && !generating;
  const sendsExternally = Boolean(provider && !provider.simulated);

  function requestGenerate() {
    if (sendsExternally && !consented) {
      setShowConsent(true);
      return;
    }
    void generate();
  }

  function addAllToBag() {
    for (const pick of picks) {
      addToBag(pick.product, { colorId: pick.colorId, size: pick.size });
    }
  }

  return (
    <>
      <div
        className={cn(
          'fixed inset-x-0 bottom-0 z-50 lg:inset-auto lg:bottom-6 lg:left-6',
          'lg:w-[350px]',
        )}
      >
        <button
          type="button"
          aria-label="Close the fitting room"
          onClick={() => setOpen(false)}
          className="fixed inset-0 -z-10 animate-fade cursor-default bg-ink-950/70 backdrop-blur-sm lg:hidden"
        />

        <section
          aria-label="Fitting room"
          className="flex max-h-[88vh] animate-sheet flex-col overflow-hidden rounded-t-panel border border-ink-700 bg-ink-850/95 shadow-2xl shadow-ink-950/70 backdrop-blur-xl lg:max-h-[calc(100vh-6rem)] lg:rounded-panel"
        >
          <header className="flex items-start justify-between gap-3 px-5 pb-3 pt-4">
            <div>
              <h2 className="font-display text-[15px] font-medium text-bone-50">Fitting room</h2>
              <p className="mt-0.5 text-[11.5px] text-bone-500">
                Tap the hanger on any product to wear it.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close the fitting room"
              className="-mr-1.5 -mt-1 grid size-8 place-items-center rounded-full text-bone-500 transition hover:text-bone-50"
            >
              <Icon name="close" size={16} />
            </button>
          </header>

          <div className="scrollarea flex-1 overflow-y-auto px-5 pb-4">
            <Stage
              stage={stage}
              error={error}
              onDismissError={dismissError}
              progress={job?.progress ?? 0}
              message={job?.stage ?? ''}
              lookSrc={activeLook?.imageUrl}
              simulated={activeLook?.simulated ?? false}
              subjectSrc={subject?.kind === 'upload' ? subject.dataUrl : DEFAULT_MODEL_IMAGE}
              hasSubject={Boolean(subject)}
              onExpand={() => setExpanded(true)}
              onCancel={() => void cancel()}
              onRetry={() => {
                dismissError();
                void generate();
              }}
            />

            {picks.length > 0 ? (
              <section className="mt-4">
                <div className="flex items-baseline justify-between">
                  <h3 className="text-eyebrow">Your picks</h3>
                  <span className="text-[11px] text-bone-500">
                    {picks.length} {picks.length === 1 ? 'piece' : 'pieces'}
                  </span>
                </div>
                <ul className="mt-2.5 flex gap-2 overflow-x-auto pb-1">
                  {picks.map((pick) => (
                    <li key={pick.product.id} className="relative shrink-0">
                      <span className="grid size-14 place-items-center rounded-lg border border-ink-700 bg-ink-800">
                        {/* eslint-disable-next-line @next/next/no-img-element -- catalogue artwork is SVG */}
                        <img
                          src={pick.product.image}
                          alt={pick.product.name}
                          title={`${pick.product.name} · ${pick.size}`}
                          className="size-11 object-contain"
                        />
                      </span>
                      <button
                        type="button"
                        onClick={() => removePick(pick.product.id)}
                        aria-label={`Remove ${pick.product.name}`}
                        className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-ink-600 bg-ink-900 text-bone-400 transition hover:border-critical hover:text-critical"
                      >
                        <Icon name="close" size={10} />
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-bone-600">
                  Add another piece and it goes on top.
                </p>
              </section>
            ) : null}

            {picks.length > 0 && stage !== 'done' && stage !== 'generating' ? (
              <div className="mt-4">
                <PhotoUploader />
              </div>
            ) : null}

            {looks.length > 1 ? (
              <section className="mt-4">
                <h3 className="text-eyebrow">This session</h3>
                <ul className="mt-2.5 flex gap-2 overflow-x-auto pb-1">
                  {looks.map((look) => (
                    <li key={look.id}>
                      <button
                        type="button"
                        onClick={() => setActiveLook(look)}
                        className={cn(
                          'block size-14 overflow-hidden rounded-lg border transition',
                          activeLook?.id === look.id
                            ? 'border-accent-500'
                            : 'border-ink-700 hover:border-ink-500',
                        )}
                        aria-label={`View look from ${new Date(look.createdAt).toLocaleTimeString()}`}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element -- session-scoped API image */}
                        <img src={look.imageUrl} alt="" className="size-full object-cover" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>

          <footer className="border-t border-ink-700/70 px-5 py-4">
            {stage === 'done' ? (
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="flex-1 rounded-lg border border-ink-600 py-2.5 text-[12.5px] text-bone-200 transition hover:border-ink-500 hover:text-bone-50"
                >
                  View & compare
                </button>
                <button
                  type="button"
                  onClick={addAllToBag}
                  className="flex-1 rounded-lg bg-bone-50 py-2.5 text-[12.5px] font-medium text-ink-900 transition hover:bg-white"
                >
                  Add to bag
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={generating ? () => void cancel() : requestGenerate}
                disabled={!canGenerate && !generating}
                className={cn(
                  'flex w-full items-center justify-center gap-2 rounded-lg py-3 text-[13px] font-medium transition',
                  generating
                    ? 'border border-ink-600 text-bone-300 hover:border-critical hover:text-critical'
                    : 'bg-accent-500 text-ink-900 hover:bg-accent-400 disabled:bg-ink-700 disabled:text-bone-600',
                )}
              >
                {generating ? (
                  'Cancel'
                ) : (
                  <>
                    <Icon name="sparkle" size={15} />
                    {looks.length > 0 ? 'Generate another' : 'Generate try-on'}
                  </>
                )}
              </button>
            )}

            {!canGenerate && !generating && stage !== 'done' ? (
              <p className="mt-2 text-center text-[11px] text-bone-600">
                {picks.length === 0 ? 'Pick a piece to begin.' : 'Add a photo to generate.'}
              </p>
            ) : null}

            <div className="mt-3 flex items-center justify-between gap-3 text-[11px]">
              <ProviderChip
                label={provider?.label ?? 'Checking provider…'}
                simulated={provider?.simulated ?? true}
                missing={provider?.missing ?? []}
              />
              <button
                type="button"
                onClick={startOver}
                className="inline-flex shrink-0 items-center gap-1.5 text-bone-500 transition hover:text-bone-100"
              >
                <Icon name="reset" size={12} />
                Start over
              </button>
            </div>
          </footer>
        </section>
      </div>

      {expanded ? (
        <LookViewer
          look={activeLook}
          onClose={() => setExpanded(false)}
          onAddAllToBag={() => {
            addAllToBag();
            setExpanded(false);
          }}
          onTryAnother={() => {
            setExpanded(false);
            setActiveLook(null);
          }}
        />
      ) : null}

      {showConsent && provider ? (
        <ConsentDialog
          providerLabel={provider.label}
          pieces={picks.length}
          onCancel={() => setShowConsent(false)}
          onConfirm={() => {
            grantConsent();
            setShowConsent(false);
            void generate();
          }}
        />
      ) : null}
    </>
  );
}

function LauncherButton({ count, onClick }: { count: number; onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="fixed bottom-5 left-5 z-50 inline-flex items-center gap-2.5 rounded-full border border-accent-500/40 bg-ink-850/95 py-3 pl-4 pr-5 text-[13px] text-bone-100 shadow-xl shadow-ink-950/60 backdrop-blur transition hover:border-accent-500"
    >
      <Icon name="hanger" size={17} className="text-accent-500" />
      Fitting room
      {count > 0 ? (
        <span className="grid size-5 place-items-center rounded-full bg-accent-500 text-[11px] font-semibold text-ink-900">
          {count}
        </span>
      ) : null}
    </button>
  );
}

/**
 * The stage keeps a portrait ratio but is capped by viewport height, so on a
 * phone the bottom sheet still shows the picks and the upload step without
 * scrolling.
 */
const STAGE_FRAME = 'mx-auto aspect-[3/4] max-h-[40vh] w-auto lg:max-h-none lg:w-full';

interface StageProps {
  stage: ReturnType<typeof useFittingRoom>['stage'];
  error: string | null;
  progress: number;
  message: string;
  lookSrc?: string;
  simulated: boolean;
  subjectSrc: string;
  hasSubject: boolean;
  onDismissError(): void;
  onExpand(): void;
  onCancel(): void;
  onRetry(): void;
}

/** The panel's image area — one element that changes character per stage. */
function Stage({
  stage,
  error,
  progress,
  message,
  lookSrc,
  simulated,
  subjectSrc,
  hasSubject,
  onDismissError,
  onExpand,
  onRetry,
}: StageProps) {
  if (stage === 'error') {
    return (
      <div className={cn(STAGE_FRAME, "flex flex-col items-center justify-center gap-3 rounded-xl border border-critical/40 bg-critical/8 px-6 text-center")}>
        <Icon name="alert" size={22} className="text-critical" />
        <p className="text-[13px] text-bone-100">{error}</p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-lg bg-bone-50 px-3.5 py-2 text-[12px] font-medium text-ink-900 transition hover:bg-white"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={onDismissError}
            className="rounded-lg border border-ink-600 px-3.5 py-2 text-[12px] text-bone-300 transition hover:text-bone-50"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  if (stage === 'generating') {
    return (
      <div className={cn(STAGE_FRAME, "relative overflow-hidden rounded-xl bg-ink-800")}>
        {hasSubject ? (
          // eslint-disable-next-line @next/next/no-img-element -- in-memory data URL
          <img src={subjectSrc} alt="" className="size-full object-cover opacity-25 blur-[3px]" />
        ) : null}

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-6 text-center">
          <span
            className="size-11 rounded-full border-2 border-ink-600 border-t-accent-500 motion-safe:animate-spin"
            style={{ animationDuration: '1.1s' }}
            aria-hidden="true"
          />
          <div>
            <p className="text-[13px] font-medium text-bone-50">Dressing your model</p>
            <p aria-live="polite" className="mt-1 text-[11.5px] text-bone-400">
              {message || 'The photo is being made for you. It takes a moment.'}
            </p>
          </div>
          <div className="h-0.5 w-40 overflow-hidden rounded-full bg-ink-600">
            <div
              className="h-full rounded-full bg-accent-500 transition-[width] duration-700 ease-[var(--ease-out-soft)]"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
        </div>
      </div>
    );
  }

  if (stage === 'done' && lookSrc) {
    return (
      <div className={cn(STAGE_FRAME, "group relative overflow-hidden rounded-xl bg-ink-800")}>
        {/* eslint-disable-next-line @next/next/no-img-element -- session-scoped API image */}
        <img src={lookSrc} alt="Your virtual try-on" className="size-full object-cover" />
        <button
          type="button"
          onClick={onExpand}
          aria-label="Open the full-size result"
          className="absolute bottom-2.5 right-2.5 grid size-8 place-items-center rounded-full bg-ink-950/70 text-bone-200 backdrop-blur transition hover:text-bone-50"
        >
          <Icon name="expand" size={15} />
        </button>
        {simulated ? (
          <span className="absolute left-2.5 top-2.5 rounded-full bg-ink-950/80 px-2 py-1 text-[10px] uppercase tracking-[0.1em] text-accent-400 backdrop-blur">
            Simulated
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn(STAGE_FRAME, "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-ink-600 bg-ink-800/40 px-6 text-center")}>
      <Icon name="hanger" size={22} className="text-bone-600" />
      <p className="text-[12.5px] text-bone-400">
        {stage === 'idle'
          ? 'Pick a piece from the grid and it appears here.'
          : 'Add a photo and we will dress you in it.'}
      </p>
    </div>
  );
}

function ProviderChip({
  label,
  simulated,
  missing,
}: {
  label: string;
  simulated: boolean;
  missing: string[];
}) {
  const title = missing.length
    ? `Not configured. Missing: ${missing.join(', ')}`
    : simulated
      ? 'Results are composited locally, not generated by AI.'
      : `Images are sent to ${label} when you generate.`;

  return (
    <span
      title={title}
      className={cn(
        'inline-flex min-w-0 items-center gap-1.5 truncate rounded-full border px-2.5 py-1',
        simulated ? 'border-ink-600 text-bone-500' : 'border-accent-700/50 text-accent-400',
      )}
    >
      <Icon name={simulated ? 'info' : 'sparkle'} size={11} className="shrink-0" />
      <span className="truncate">{simulated ? 'Local preview' : label}</span>
    </span>
  );
}

function ConsentDialog({
  providerLabel,
  pieces,
  onCancel,
  onConfirm,
}: {
  providerLabel: string;
  pieces: number;
  onCancel(): void;
  onConfirm(): void;
}) {
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Cancel"
        onClick={onCancel}
        className="absolute inset-0 animate-fade cursor-default bg-ink-950/80 backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="consent-title"
        className="relative w-full max-w-sm animate-sheet rounded-panel border border-ink-700 bg-ink-850 p-6"
      >
        <h2 id="consent-title" className="font-display text-[16px] font-medium text-bone-50">
          Send your photo to {providerLabel}?
        </h2>
        <p className="mt-3 text-[12.5px] leading-relaxed text-bone-300">
          To render the try-on, your photo and the {pieces === 1 ? 'product image' : `${pieces} product images`}{' '}
          are sent to {providerLabel}. Nothing has been sent so far. Your photo is not stored by this
          store beyond your current session.
        </p>
        <p className="mt-3 text-[11.5px] text-bone-600">
          Check {providerLabel}&rsquo;s own terms for how they handle uploaded images.
        </p>
        <div className="mt-6 flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-lg border border-ink-600 py-2.5 text-[12.5px] text-bone-300 transition hover:text-bone-50"
          >
            Not now
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="flex-1 rounded-lg bg-accent-500 py-2.5 text-[12.5px] font-medium text-ink-900 transition hover:bg-accent-400"
          >
            Send and generate
          </button>
        </div>
      </div>
    </div>
  );
}
