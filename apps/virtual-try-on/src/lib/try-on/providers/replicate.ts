import {
  type InlineImage,
  type PreparedTryOnRequest,
  type ProviderAsset,
  type ProviderConfiguration,
  type ProviderContext,
  type ProviderJobRef,
  type ProviderJobUpdate,
  TryOnProviderError,
  type VirtualTryOnProvider,
} from '../provider';
import type { TryOnCapabilities } from '../types';

/**
 * Replicate adapter — for hosted try-on models (IDM-VTON, CatVTON and similar).
 *
 * Replicate exposes a genuine prediction queue, which is the shape this
 * interface was designed around: `startJob` creates the prediction, `pollJob`
 * reads it back, `cancelJob` stops it.
 *
 * The model is not hard-coded. Set REPLICATE_TRYON_MODEL to an
 * `owner/name` or `owner/name:version` reference, and map its input field names
 * with REPLICATE_TRYON_INPUT_MAP if they differ from the defaults.
 */

const API = 'https://api.replicate.com/v1';

interface InputMap {
  person: string;
  garment: string;
  description: string;
}

const DEFAULT_INPUT_MAP: InputMap = {
  person: 'human_img',
  garment: 'garm_img',
  description: 'garment_des',
};

export class ReplicateTryOnProvider implements VirtualTryOnProvider {
  readonly id = 'replicate';
  readonly label = 'Replicate';
  readonly simulated = false;

  readonly capabilities: TryOnCapabilities = {
    // Hosted VTON models take one garment per prediction; we chain them.
    maxGarments: 3,
    preservesBackground: true,
    timeoutMs: 180_000,
    acceptedMimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
    maxSubjectBytes: 10 * 1024 * 1024,
  };

  private get token() {
    return process.env.REPLICATE_API_TOKEN || undefined;
  }

  private get model() {
    return process.env.REPLICATE_TRYON_MODEL || undefined;
  }

  private get inputMap(): InputMap {
    const raw = process.env.REPLICATE_TRYON_INPUT_MAP;
    if (!raw) return DEFAULT_INPUT_MAP;
    try {
      return { ...DEFAULT_INPUT_MAP, ...(JSON.parse(raw) as Partial<InputMap>) };
    } catch {
      return DEFAULT_INPUT_MAP;
    }
  }

  configuration(): ProviderConfiguration {
    const missing: string[] = [];
    if (!this.token) missing.push('REPLICATE_API_TOKEN');
    if (!this.model) missing.push('REPLICATE_TRYON_MODEL');
    return {
      configured: missing.length === 0,
      missing,
      notice: missing.length
        ? 'Set REPLICATE_API_TOKEN and REPLICATE_TRYON_MODEL to enable live generation.'
        : undefined,
    };
  }

  async uploadImage(image: InlineImage): Promise<ProviderAsset> {
    if (image.mimeType === 'image/svg+xml') {
      throw new TryOnProviderError(
        'unsupported_image',
        'Replicate models cannot read SVG artwork. Rasterise garment images to PNG before sending.',
      );
    }
    // Replicate accepts data URIs for file inputs, which avoids a second
    // round-trip through their upload endpoint.
    return {
      kind: 'url',
      url: `data:${image.mimeType};base64,${Buffer.from(image.bytes).toString('base64')}`,
      mimeType: image.mimeType,
    };
  }

  async startJob(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<ProviderJobRef> {
    const first = request.garments[0];
    if (!first) throw new TryOnProviderError('invalid_request', 'Pick at least one piece to try on.');

    const prediction = await this.createPrediction(
      assetUrl(request.subject),
      assetUrl(first.asset),
      describe(first.garment),
      ctx,
    );

    return {
      id: prediction.id,
      meta: {
        // Remaining garments are applied one after another, each onto the
        // previous render — this is how layering works on single-garment models.
        queue: request.garments.slice(1).map((entry) => ({
          url: assetUrl(entry.asset),
          description: describe(entry.garment),
        })),
        index: 0,
        total: request.garments.length,
      },
    };
  }

  async pollJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<ProviderJobUpdate> {
    const prediction = await this.request<Prediction>(`/predictions/${ref.id}`, { signal: ctx.signal });
    const meta = (ref.meta ?? {}) as { queue?: QueueEntry[]; index?: number; total?: number };
    const index = meta.index ?? 0;
    const total = meta.total ?? 1;
    const share = 1 / total;
    const base = 0.3 + 0.65 * (index * share);

    switch (prediction.status) {
      case 'starting':
        return { status: 'running', progress: base + share * 0.1, stage: 'Waiting for a GPU' };
      case 'processing':
        return {
          status: 'running',
          progress: base + share * 0.45,
          stage: total > 1 ? `Fitting piece ${index + 1} of ${total}` : 'Fitting the garment',
        };
      case 'canceled':
        return { status: 'cancelled' };
      case 'failed':
        return {
          status: 'failed',
          error: {
            code: 'provider_error',
            message: prediction.error ?? 'The model failed to render this look.',
            retryable: true,
          },
        };
      case 'succeeded': {
        const output = outputUrl(prediction.output);
        if (!output) {
          return {
            status: 'failed',
            error: { code: 'provider_error', message: 'The model returned no image.', retryable: true },
          };
        }

        const queue = meta.queue ?? [];
        const next = queue[0];
        if (next) {
          // Chain the next layer onto the render we just received.
          const chained = await this.createPrediction(output, next.url, next.description, ctx);
          ref.id = chained.id;
          ref.meta = { queue: queue.slice(1), index: index + 1, total };
          return {
            status: 'running',
            progress: base + share,
            stage: `Layering piece ${index + 2} of ${total}`,
          };
        }

        const image = await download(output, ctx.signal);
        return { status: 'succeeded', progress: 1, stage: 'Finishing', image };
      }
      default:
        return { status: 'running', progress: base, stage: 'Working' };
    }
  }

  async cancelJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<void> {
    await this.request(`/predictions/${ref.id}/cancel`, { method: 'POST', signal: ctx.signal }).catch(
      () => {},
    );
  }

  private async createPrediction(
    personUrl: string,
    garmentUrl: string,
    description: string,
    ctx: ProviderContext,
  ): Promise<Prediction> {
    const map = this.inputMap;
    const input: Record<string, unknown> = {
      [map.person]: personUrl,
      [map.garment]: garmentUrl,
      [map.description]: description,
    };

    const model = this.model!;
    const [reference, version] = model.split(':');
    const path = version ? '/predictions' : `/models/${reference}/predictions`;
    const body = version ? { version, input } : { input };

    return this.request<Prediction>(path, {
      method: 'POST',
      body: JSON.stringify(body),
      signal: ctx.signal,
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const token = this.token;
    if (!token) throw new TryOnProviderError('not_configured', 'REPLICATE_API_TOKEN is not set.');

    const response = await fetch(`${API}${path}`, {
      ...init,
      headers: {
        authorization: `Bearer ${token}`,
        'content-type': 'application/json',
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      if (response.status === 429) {
        throw new TryOnProviderError('rate_limited', 'Replicate is rate limiting requests.', true);
      }
      if (response.status === 401 || response.status === 403) {
        throw new TryOnProviderError('not_configured', 'Replicate rejected the API token.');
      }
      if (response.status === 422) {
        throw new TryOnProviderError(
          'invalid_request',
          `Replicate rejected the input. Check REPLICATE_TRYON_INPUT_MAP against the model's schema. ${detail.slice(0, 180)}`,
        );
      }
      throw new TryOnProviderError(
        'provider_error',
        `Replicate error ${response.status}: ${detail.slice(0, 180)}`,
        true,
      );
    }

    return (await response.json()) as T;
  }
}

interface QueueEntry {
  url: string;
  description: string;
}

interface Prediction {
  id: string;
  status: 'starting' | 'processing' | 'succeeded' | 'failed' | 'canceled';
  output?: unknown;
  error?: string;
}

function assetUrl(asset: ProviderAsset): string {
  if (asset.kind === 'url') return asset.url;
  return `data:${asset.image.mimeType};base64,${Buffer.from(asset.image.bytes).toString('base64')}`;
}

function describe(garment: PreparedTryOnRequest['garments'][number]['garment']): string {
  return [garment.colorLabel, garment.name].filter(Boolean).join(' ');
}

function outputUrl(output: unknown): string | undefined {
  if (typeof output === 'string') return output;
  if (Array.isArray(output)) {
    const last = [...output].reverse().find((item) => typeof item === 'string');
    return typeof last === 'string' ? last : undefined;
  }
  return undefined;
}

async function download(url: string, signal: AbortSignal): Promise<InlineImage> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new TryOnProviderError('provider_error', `Could not download the result (${response.status}).`, true);
  }
  const mimeType = response.headers.get('content-type') ?? 'image/png';
  return {
    bytes: new Uint8Array(await response.arrayBuffer()),
    mimeType,
    filename: 'try-on.png',
  };
}
