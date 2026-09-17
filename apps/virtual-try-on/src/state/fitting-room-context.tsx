'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import { DEFAULT_MODEL_IMAGE, type Product } from '@/data/catalog';
import { inlineAsset, rasterizeGarment } from '@/lib/image-client';
import { createSessionStore } from '@/lib/session-store';
import type { TryOnCapabilities, TryOnJob, TryOnProviderInfo, TryOnRequest } from '@/lib/try-on/types';

/**
 * Fitting-room state.
 *
 * Owns the shopper's picks, their photo, the in-flight job and the looks they
 * have generated this session. Nothing here talks to a model directly — it
 * calls this app's own API, which is the only place a provider key exists.
 */

export interface Pick {
  product: Product;
  colorId: string;
  size: string;
}

/** What actually persists: products are resolved from the catalogue on read. */
interface StoredPick {
  productId: string;
  colorId: string;
  size: string;
}

export interface Subject {
  kind: 'upload' | 'demo-model';
  dataUrl: string;
  width: number;
  height: number;
  label: string;
}

export interface Look {
  id: string;
  imageUrl: string;
  createdAt: number;
  simulated: boolean;
  providerLabel: string;
  garmentNames: string[];
  subjectDataUrl: string;
  note?: string;
}

export type FittingStage = 'idle' | 'needs-photo' | 'ready' | 'generating' | 'done' | 'error';

const picksStore = createSessionStore<StoredPick[]>('vto.picks', []);
const subjectStore = createSessionStore<Subject | null>('vto.subject', null);
const looksStore = createSessionStore<Look[]>('vto.looks', []);
const consentStore = createSessionStore<boolean>('vto.consent', false);

const POLL_MS = 900;
const MAX_LOOKS = 12;

interface FittingRoomValue {
  open: boolean;
  picks: Pick[];
  subject: Subject | null;
  job: TryOnJob | null;
  looks: Look[];
  activeLook: Look | null;
  provider: TryOnProviderInfo | null;
  consented: boolean;
  stage: FittingStage;
  error: string | null;

  setOpen(open: boolean): void;
  togglePick(product: Product, options?: { colorId?: string; size?: string }): void;
  hasPick(productId: string): boolean;
  removePick(productId: string): void;
  setSubject(subject: Subject | null): void;
  useDemoModel(): void;
  grantConsent(): void;
  generate(): Promise<void>;
  cancel(): Promise<void>;
  setActiveLook(look: Look | null): void;
  startOver(): void;
  dismissError(): void;
}

const FittingRoomContext = createContext<FittingRoomValue | null>(null);

export function FittingRoomProvider({
  children,
  catalog,
}: {
  children: React.ReactNode;
  catalog: Product[];
}) {
  const storedPicks = useSyncExternalStore(
    picksStore.subscribe,
    picksStore.getSnapshot,
    picksStore.getServerSnapshot,
  );
  const subject = useSyncExternalStore(
    subjectStore.subscribe,
    subjectStore.getSnapshot,
    subjectStore.getServerSnapshot,
  );
  const looks = useSyncExternalStore(
    looksStore.subscribe,
    looksStore.getSnapshot,
    looksStore.getServerSnapshot,
  );
  const consented = useSyncExternalStore(
    consentStore.subscribe,
    consentStore.getSnapshot,
    consentStore.getServerSnapshot,
  );

  const [open, setOpen] = useState(false);
  const [job, setJob] = useState<TryOnJob | null>(null);
  const [activeLookId, setActiveLookId] = useState<string | null>(null);
  const [provider, setProvider] = useState<TryOnProviderInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobIdRef = useRef<string | null>(null);

  const picks = useMemo(
    () =>
      storedPicks
        .map((entry) => {
          const product = catalog.find((item) => item.id === entry.productId);
          return product ? { product, colorId: entry.colorId, size: entry.size } : null;
        })
        .filter((pick): pick is Pick => pick !== null),
    [catalog, storedPicks],
  );

  // Only an explicitly selected look is shown, so clearing the selection
  // returns the panel to its empty state rather than re-showing the last render.
  const activeLook = useMemo(
    () => (activeLookId ? (looks.find((look) => look.id === activeLookId) ?? null) : null),
    [activeLookId, looks],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/try-on/config', { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((info: TryOnProviderInfo | null) => {
        if (info) setProvider(info);
      })
      .catch(() => {
        // The panel falls back to generic copy when this fails.
      });
    return () => controller.abort();
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const togglePick = useCallback<FittingRoomValue['togglePick']>(
    (product, options) => {
      setError(null);
      picksStore.set((current) => {
        if (current.some((pick) => pick.productId === product.id)) {
          return current.filter((pick) => pick.productId !== product.id);
        }
        // Only one piece per layer can be worn, so a new coat replaces the old.
        const kept = current.filter(
          (pick) => catalog.find((item) => item.id === pick.productId)?.layer !== product.layer,
        );
        return [
          ...kept,
          {
            productId: product.id,
            colorId: options?.colorId ?? product.colors[0]?.id ?? 'default',
            size: options?.size ?? product.sizes[Math.floor(product.sizes.length / 2)] ?? 'One size',
          },
        ];
      });
      setActiveLookId(null);
      setOpen(true);
    },
    [catalog],
  );

  const hasPick = useCallback(
    (productId: string) => storedPicks.some((pick) => pick.productId === productId),
    [storedPicks],
  );

  const removePick = useCallback((productId: string) => {
    picksStore.set((current) => current.filter((pick) => pick.productId !== productId));
  }, []);

  const setSubject = useCallback((next: Subject | null) => {
    setError(null);
    subjectStore.set(next);
  }, []);

  const useDemoModel = useCallback(() => {
    setError(null);
    subjectStore.set({
      kind: 'demo-model',
      dataUrl: '',
      width: 800,
      height: 1200,
      label: 'Studio figure',
    });
  }, []);

  const grantConsent = useCallback(() => consentStore.set(true), []);

  const cancel = useCallback(async () => {
    stopPolling();
    const id = jobIdRef.current;
    jobIdRef.current = null;
    if (!id) return;
    setJob(null);
    await fetch(`/api/try-on/jobs/${id}`, { method: 'DELETE' }).catch(() => {});
  }, [stopPolling]);

  const generate = useCallback(async () => {
    const currentPicks = picksStore
      .get()
      .map((entry) => {
        const product = catalog.find((item) => item.id === entry.productId);
        return product ? { product, colorId: entry.colorId, size: entry.size } : null;
      })
      .filter((pick): pick is Pick => pick !== null);

    const currentSubject = subjectStore.get();
    if (!currentSubject || currentPicks.length === 0) return;

    setError(null);
    setActiveLookId(null);
    stopPolling();

    let request: TryOnRequest;
    try {
      request = await buildRequest(currentSubject, currentPicks, provider?.capabilities);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Those images could not be prepared.');
      return;
    }

    try {
      const response = await fetch('/api/try-on/jobs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { error?: { message?: string } }
          | null;
        throw new Error(payload?.error?.message ?? 'The try-on could not be started.');
      }

      const started = (await response.json()) as TryOnJob;
      jobIdRef.current = started.id;
      setJob(started);
      poll(started.id, request.subject.dataUrl, currentPicks);
    } catch (cause) {
      setJob(null);
      setError(cause instanceof Error ? cause.message : 'The try-on could not be started.');
    }

    function poll(id: string, subjectSrc: string, activePicks: Pick[]) {
      pollRef.current = setTimeout(async () => {
        if (jobIdRef.current !== id) return;
        try {
          const response = await fetch(`/api/try-on/jobs/${id}`, { cache: 'no-store' });
          if (!response.ok) throw new Error('That try-on expired. Generate a new one.');

          const next = (await response.json()) as TryOnJob;
          setJob(next);

          if (next.status === 'succeeded' && next.result) {
            jobIdRef.current = null;
            const look: Look = {
              id: next.id,
              imageUrl: next.result.imageUrl,
              createdAt: Date.now(),
              simulated: next.result.simulated,
              providerLabel: next.result.providerLabel,
              garmentNames: activePicks.map((pick) => pick.product.name),
              subjectDataUrl: subjectSrc,
              note: next.result.note,
            };
            looksStore.set((current) => [look, ...current].slice(0, MAX_LOOKS));
            setActiveLookId(look.id);
            return;
          }

          if (next.status === 'failed') {
            jobIdRef.current = null;
            setError(next.error?.message ?? 'The try-on failed.');
            return;
          }

          if (next.status === 'cancelled') {
            jobIdRef.current = null;
            setJob(null);
            return;
          }

          poll(id, subjectSrc, activePicks);
        } catch (cause) {
          jobIdRef.current = null;
          setError(cause instanceof Error ? cause.message : 'Lost contact with the fitting room.');
        }
      }, POLL_MS);
    }
  }, [catalog, provider?.capabilities, stopPolling]);

  const setActiveLook = useCallback((look: Look | null) => setActiveLookId(look?.id ?? null), []);

  const startOver = useCallback(() => {
    void cancel();
    picksStore.set([]);
    subjectStore.set(null);
    looksStore.set([]);
    setActiveLookId(null);
    setError(null);
    setJob(null);
  }, [cancel]);

  const stage: FittingStage = useMemo(() => {
    if (error) return 'error';
    if (job && (job.status === 'queued' || job.status === 'running')) return 'generating';
    if (activeLook) return 'done';
    if (picks.length === 0) return 'idle';
    if (!subject) return 'needs-photo';
    return 'ready';
  }, [activeLook, error, job, picks.length, subject]);

  const value = useMemo<FittingRoomValue>(
    () => ({
      open,
      picks,
      subject,
      job,
      looks,
      activeLook,
      provider,
      consented,
      stage,
      error,
      setOpen,
      togglePick,
      hasPick,
      removePick,
      setSubject,
      useDemoModel,
      grantConsent,
      generate,
      cancel,
      setActiveLook,
      startOver,
      dismissError: () => setError(null),
    }),
    [
      open,
      picks,
      subject,
      job,
      looks,
      activeLook,
      provider,
      consented,
      stage,
      error,
      togglePick,
      hasPick,
      removePick,
      setSubject,
      useDemoModel,
      grantConsent,
      generate,
      cancel,
      setActiveLook,
      startOver,
    ],
  );

  return <FittingRoomContext.Provider value={value}>{children}</FittingRoomContext.Provider>;
}

export function useFittingRoom(): FittingRoomValue {
  const value = useContext(FittingRoomContext);
  if (!value) throw new Error('useFittingRoom must be used inside <FittingRoomProvider>');
  return value;
}

/**
 * Turns picks into a provider-ready request: garments ordered bottom-of-outfit
 * first, artwork in a format the provider can read, and the demo figure loaded
 * on demand.
 *
 * Image models reject SVG, so catalogue artwork is rasterised for them. The
 * local preview reads SVG natively, and keeping the vector there is both
 * sharper and cheaper.
 */
async function buildRequest(
  subject: Subject,
  picks: Pick[],
  capabilities?: TryOnCapabilities,
): Promise<TryOnRequest> {
  const acceptsVector = capabilities?.acceptedMimeTypes.includes('image/svg+xml') ?? false;
  const prepare = (url: string, edge?: number) =>
    acceptsVector ? inlineAsset(url) : rasterizeGarment(url, edge);

  const ordered = [...picks].sort((a, b) => a.product.layerRank - b.product.layerRank);

  const garments = await Promise.all(
    ordered.map(async (pick) => ({
      productId: pick.product.id,
      name: pick.product.name,
      category: pick.product.category,
      layer: pick.product.layer,
      imageUrl: await prepare(pick.product.image),
      colorLabel: pick.product.colors.find((color) => color.id === pick.colorId)?.label,
      size: pick.size,
    })),
  );

  if (subject.kind === 'demo-model' && !subject.dataUrl) {
    const figure = await prepare(DEFAULT_MODEL_IMAGE, 1200);
    return {
      subject: { kind: 'demo-model', dataUrl: figure, width: 800, height: 1200 },
      garments,
    };
  }

  return {
    subject: {
      kind: subject.kind,
      dataUrl: subject.dataUrl,
      width: subject.width,
      height: subject.height,
    },
    garments,
  };
}
