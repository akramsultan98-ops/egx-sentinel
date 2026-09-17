import type { TryOnCapabilities, TryOnError, TryOnErrorCode, TryOnRequest } from './types';

/** A decoded image, ready to hand to a provider. */
export interface InlineImage {
  bytes: Uint8Array;
  mimeType: string;
  /** Stable name used for multipart uploads and provider-side filenames. */
  filename: string;
}

/**
 * What `uploadImage` returns. Providers that accept inline base64 (Gemini)
 * return the bytes untouched; providers that need a fetchable URL (Replicate)
 * return one.
 */
export type ProviderAsset =
  | { kind: 'inline'; image: InlineImage }
  | { kind: 'url'; url: string; mimeType: string };

export interface PreparedTryOnRequest {
  subject: ProviderAsset;
  garments: Array<{ asset: ProviderAsset; garment: TryOnRequest['garments'][number] }>;
  notes?: string;
}

/** Opaque handle to work in flight at the provider. */
export interface ProviderJobRef {
  id: string;
  /** Provider-specific bag; never inspected outside the adapter that made it. */
  meta?: Record<string, unknown>;
}

export interface ProviderJobUpdate {
  status: 'running' | 'succeeded' | 'failed' | 'cancelled';
  /** 0..1 when the provider reports it. */
  progress?: number;
  stage?: string;
  image?: InlineImage;
  note?: string;
  error?: TryOnError;
}

export interface ProviderContext {
  signal: AbortSignal;
  /** Push a shopper-facing progress update. Safe to call often. */
  report(progress: number, stage: string): void;
}

export interface ProviderConfiguration {
  configured: boolean;
  /** Environment variables that are required but unset. */
  missing: string[];
  notice?: string;
}

/**
 * The contract every try-on backend implements.
 *
 * Deliberately split into upload / start / poll / cancel rather than one
 * `generate()` call: real try-on services are asynchronous jobs, and the
 * storefront polls our own API rather than holding a request open.
 */
export interface VirtualTryOnProvider {
  readonly id: string;
  readonly label: string;
  readonly simulated: boolean;
  readonly capabilities: TryOnCapabilities;

  /** Checked before any work starts, so misconfiguration fails loudly. */
  configuration(): ProviderConfiguration;

  /** Normalise one image into whatever this provider consumes. */
  uploadImage(image: InlineImage, ctx: ProviderContext): Promise<ProviderAsset>;

  startJob(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<ProviderJobRef>;

  pollJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<ProviderJobUpdate>;

  cancelJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<void>;
}

export class TryOnProviderError extends Error {
  readonly code: TryOnErrorCode;
  readonly retryable: boolean;

  constructor(code: TryOnErrorCode, message: string, retryable = false) {
    super(message);
    this.name = 'TryOnProviderError';
    this.code = code;
    this.retryable = retryable;
  }

  toTryOnError(): TryOnError {
    return { code: this.code, message: this.message, retryable: this.retryable };
  }
}

export function toTryOnError(cause: unknown): TryOnError {
  if (cause instanceof TryOnProviderError) return cause.toTryOnError();
  if (cause instanceof DOMException && cause.name === 'AbortError') {
    return { code: 'cancelled', message: 'The try-on was cancelled.', retryable: true };
  }
  if (cause instanceof Error) {
    return { code: 'unknown', message: cause.message, retryable: true };
  }
  return { code: 'unknown', message: 'Something went wrong.', retryable: true };
}

/** Result of a completed run, before it is turned into a `TryOnResult`. */
export interface ExecutedTryOn {
  image: InlineImage;
  note?: string;
  latencyMs: number;
}

const POLL_INTERVAL_MS = 900;
const POLL_BACKOFF = 1.15;
const POLL_MAX_MS = 4000;

/**
 * Drives any provider through the full lifecycle: upload every image, start the
 * job, poll until terminal, return the bytes. Providers only implement the four
 * primitives; the retry/backoff/timeout policy lives here so it is identical
 * across backends.
 */
export async function executeTryOn(
  provider: VirtualTryOnProvider,
  request: TryOnRequest,
  ctx: ProviderContext,
): Promise<ExecutedTryOn> {
  const startedAt = Date.now();
  const config = provider.configuration();
  if (!config.configured) {
    throw new TryOnProviderError(
      'not_configured',
      `${provider.label} is not configured. Missing: ${config.missing.join(', ') || 'unknown'}.`,
    );
  }

  ctx.report(0.06, 'Reading your photo');
  const subject = await provider.uploadImage(dataUrlToImage(request.subject.dataUrl, 'subject'), ctx);

  ctx.report(0.16, 'Preparing the pieces');
  const garments: PreparedTryOnRequest['garments'] = [];
  for (const [index, garment] of request.garments.entries()) {
    const image = await loadGarmentImage(garment.imageUrl, `garment-${index}`);
    garments.push({ asset: await provider.uploadImage(image, ctx), garment });
  }

  ctx.report(0.26, 'Sending to the studio');
  const ref = await provider.startJob({ subject, garments, notes: request.notes }, ctx);

  const deadline = startedAt + provider.capabilities.timeoutMs;
  let wait = POLL_INTERVAL_MS;

  try {
    for (;;) {
      if (ctx.signal.aborted) {
        await provider.cancelJob(ref, ctx).catch(() => {});
        throw new TryOnProviderError('cancelled', 'The try-on was cancelled.', true);
      }
      if (Date.now() > deadline) {
        await provider.cancelJob(ref, ctx).catch(() => {});
        throw new TryOnProviderError(
          'timeout',
          `${provider.label} did not return a result in time.`,
          true,
        );
      }

      const update = await provider.pollJob(ref, ctx);

      if (update.progress !== undefined || update.stage) {
        ctx.report(
          update.progress ?? 0.5,
          update.stage ?? 'Rendering your look',
        );
      }

      if (update.status === 'succeeded') {
        if (!update.image) {
          throw new TryOnProviderError('provider_error', 'The provider returned no image.', true);
        }
        return { image: update.image, note: update.note, latencyMs: Date.now() - startedAt };
      }
      if (update.status === 'failed') {
        throw update.error
          ? new TryOnProviderError(update.error.code, update.error.message, update.error.retryable)
          : new TryOnProviderError('provider_error', `${provider.label} failed.`, true);
      }
      if (update.status === 'cancelled') {
        throw new TryOnProviderError('cancelled', 'The try-on was cancelled.', true);
      }

      await sleep(wait, ctx.signal);
      wait = Math.min(wait * POLL_BACKOFF, POLL_MAX_MS);
    }
  } finally {
    // Nothing to clean up for inline providers; polling providers cancel above.
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new TryOnProviderError('cancelled', 'The try-on was cancelled.', true));
    }
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

const DATA_URL = /^data:([^;,]+)(;base64)?,(.*)$/s;

export function dataUrlToImage(dataUrl: string, filename: string): InlineImage {
  const match = DATA_URL.exec(dataUrl);
  if (!match) {
    throw new TryOnProviderError('unsupported_image', 'The photo could not be read.');
  }
  const [, mimeType, base64, payload] = match;
  const bytes = base64
    ? Uint8Array.from(Buffer.from(payload, 'base64'))
    : new TextEncoder().encode(decodeURIComponent(payload));
  return { bytes, mimeType, filename: `${filename}${extensionFor(mimeType)}` };
}

export function imageToDataUrl(image: InlineImage): string {
  return `data:${image.mimeType};base64,${Buffer.from(image.bytes).toString('base64')}`;
}

function extensionFor(mimeType: string): string {
  if (mimeType.includes('png')) return '.png';
  if (mimeType.includes('webp')) return '.webp';
  if (mimeType.includes('svg')) return '.svg';
  return '.jpg';
}

/**
 * Garment artwork lives in `public/`, so it is read off disk rather than
 * fetched over HTTP — the server has no reliable absolute URL for itself and
 * a self-request would deadlock on a single-worker deployment.
 */
async function loadGarmentImage(imageUrl: string, filename: string): Promise<InlineImage> {
  if (imageUrl.startsWith('data:')) return dataUrlToImage(imageUrl, filename);

  if (/^https?:\/\//.test(imageUrl)) {
    const response = await fetch(imageUrl);
    if (!response.ok) {
      throw new TryOnProviderError('provider_error', `Could not load garment image (${response.status}).`);
    }
    const mimeType = response.headers.get('content-type') ?? 'image/png';
    const bytes = new Uint8Array(await response.arrayBuffer());
    return { bytes, mimeType, filename: `${filename}${extensionFor(mimeType)}` };
  }

  const { readFile } = await import('node:fs/promises');
  const { join, normalize } = await import('node:path');
  const relative = normalize(imageUrl).replace(/^([/\\]|\.\.)+/, '');
  const absolute = join(process.cwd(), 'public', relative);
  const bytes = new Uint8Array(await readFile(absolute));
  const mimeType = imageUrl.endsWith('.svg')
    ? 'image/svg+xml'
    : imageUrl.endsWith('.png')
      ? 'image/png'
      : 'image/jpeg';
  return { bytes, mimeType, filename: `${filename}${extensionFor(mimeType)}` };
}
