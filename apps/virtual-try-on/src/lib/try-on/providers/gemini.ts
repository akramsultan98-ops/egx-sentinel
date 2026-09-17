import {
  type InlineImage,
  type PreparedTryOnRequest,
  type ProviderAsset,
  type ProviderContext,
  type ProviderConfiguration,
  type ProviderJobRef,
  type ProviderJobUpdate,
  TryOnProviderError,
  type VirtualTryOnProvider,
} from '../provider';
import type { TryOnCapabilities } from '../types';

/**
 * Google Gemini image model adapter.
 *
 * Gemini answers a single request rather than exposing a job queue, so
 * `startJob` kicks the request off and parks the promise; `pollJob` reports on
 * it. That keeps the storefront's polling contract identical across providers.
 */

const ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models';
const DEFAULT_MODEL = 'gemini-2.5-flash-image';

interface Pending {
  promise: Promise<InlineImage>;
  settled: 'pending' | 'done' | 'error';
  image?: InlineImage;
  error?: unknown;
  startedAt: number;
}

const pending = new Map<string, Pending>();

export class GeminiTryOnProvider implements VirtualTryOnProvider {
  readonly id = 'gemini';
  readonly label = 'Google Gemini';
  readonly simulated = false;

  readonly capabilities: TryOnCapabilities = {
    maxGarments: 4,
    preservesBackground: true,
    timeoutMs: 120_000,
    acceptedMimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
    maxSubjectBytes: 8 * 1024 * 1024,
  };

  private get apiKey(): string | undefined {
    return process.env.GEMINI_API_KEY || process.env.GOOGLE_AI_API_KEY || undefined;
  }

  private get model(): string {
    return process.env.GEMINI_IMAGE_MODEL || DEFAULT_MODEL;
  }

  configuration(): ProviderConfiguration {
    const missing = this.apiKey ? [] : ['GEMINI_API_KEY'];
    return {
      configured: missing.length === 0,
      missing,
      notice: missing.length ? 'Set GEMINI_API_KEY to enable live generation.' : undefined,
    };
  }

  async uploadImage(image: InlineImage): Promise<ProviderAsset> {
    if (image.mimeType === 'image/svg+xml') {
      throw new TryOnProviderError(
        'unsupported_image',
        'Gemini cannot read SVG artwork. Rasterise garment images to PNG before sending.',
      );
    }
    // Gemini takes images inline as base64, so there is nothing to upload.
    return { kind: 'inline', image };
  }

  async startJob(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<ProviderJobRef> {
    const id = `gemini_${Math.random().toString(36).slice(2)}`;
    const entry: Pending = {
      settled: 'pending',
      startedAt: Date.now(),
      promise: this.generate(request, ctx),
    };
    entry.promise.then(
      (image) => {
        entry.settled = 'done';
        entry.image = image;
      },
      (error) => {
        entry.settled = 'error';
        entry.error = error;
      },
    );
    pending.set(id, entry);
    return { id };
  }

  async pollJob(ref: ProviderJobRef): Promise<ProviderJobUpdate> {
    const entry = pending.get(ref.id);
    if (!entry) {
      return {
        status: 'failed',
        error: { code: 'provider_error', message: 'The generation was lost.', retryable: true },
      };
    }

    if (entry.settled === 'done' && entry.image) {
      pending.delete(ref.id);
      return { status: 'succeeded', progress: 1, stage: 'Finishing', image: entry.image };
    }
    if (entry.settled === 'error') {
      pending.delete(ref.id);
      throw entry.error;
    }

    // Gemini gives no progress signal, so approach 0.9 asymptotically on time.
    const elapsed = Date.now() - entry.startedAt;
    const progress = 0.3 + 0.6 * (1 - Math.exp(-elapsed / 18_000));
    return { status: 'running', progress, stage: stageFor(elapsed) };
  }

  async cancelJob(ref: ProviderJobRef): Promise<void> {
    pending.delete(ref.id);
  }

  private async generate(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<InlineImage> {
    const key = this.apiKey;
    if (!key) throw new TryOnProviderError('not_configured', 'GEMINI_API_KEY is not set.');

    const parts: unknown[] = [{ text: buildPrompt(request) }];
    parts.push(inlinePart(request.subject));
    for (const entry of request.garments) parts.push(inlinePart(entry.asset));

    const response = await fetch(`${ENDPOINT}/${this.model}:generateContent`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({
        contents: [{ role: 'user', parts }],
        generationConfig: { responseModalities: ['IMAGE'] },
      }),
      signal: ctx.signal,
    });

    if (!response.ok) throw await geminiError(response);

    const payload = (await response.json()) as GeminiResponse;
    const candidate = payload.candidates?.[0];

    if (candidate?.finishReason === 'SAFETY' || payload.promptFeedback?.blockReason) {
      throw new TryOnProviderError(
        'content_rejected',
        'The model declined this photo. Try a clear, fully-clothed photo of yourself.',
      );
    }

    const imagePart = candidate?.content?.parts?.find((part) => part.inlineData?.data);
    if (!imagePart?.inlineData) {
      throw new TryOnProviderError('provider_error', 'Gemini returned no image.', true);
    }

    return {
      bytes: Uint8Array.from(Buffer.from(imagePart.inlineData.data, 'base64')),
      mimeType: imagePart.inlineData.mimeType || 'image/png',
      filename: 'try-on.png',
    };
  }
}

function inlinePart(asset: ProviderAsset) {
  if (asset.kind !== 'inline') {
    throw new TryOnProviderError('provider_error', 'Gemini expects inline image data.');
  }
  return {
    inline_data: {
      mime_type: asset.image.mimeType,
      data: Buffer.from(asset.image.bytes).toString('base64'),
    },
  };
}

function buildPrompt(request: PreparedTryOnRequest): string {
  const pieces = request.garments
    .map((entry, index) => {
      const g = entry.garment;
      const detail = [g.colorLabel, g.category].filter(Boolean).join(', ');
      return `${index + 2}. ${g.name}${detail ? ` (${detail})` : ''} — worn as the ${g.layer} layer`;
    })
    .join('\n');

  return [
    'You are a virtual fitting-room renderer for a fashion retailer.',
    '',
    'Image 1 is the customer. The images that follow are flat-lay product shots:',
    pieces,
    '',
    'Produce a single photorealistic image of the person from image 1 wearing those garments,',
    'layered in the order listed. Keep their face, hair, skin tone, body proportions, pose and',
    'the original background exactly as they are. Match each garment’s colour, fabric texture,',
    'print and proportions to its product shot, and drape it with believable folds, shadows and',
    'contact with the body. Do not restyle, retouch or beautify the person. Do not add logos,',
    'text or accessories that are not shown. Return only the image.',
    request.notes ? `\nCustomer note: ${request.notes}` : '',
  ].join('\n');
}

function stageFor(elapsed: number): string {
  if (elapsed < 6000) return 'Reading your proportions';
  if (elapsed < 14_000) return 'Draping the fabric';
  if (elapsed < 26_000) return 'Matching light and shadow';
  return 'Finishing the render';
}

async function geminiError(response: Response): Promise<TryOnProviderError> {
  const body = await response.text().catch(() => '');
  const message = extractMessage(body) ?? response.statusText;
  if (response.status === 429) {
    return new TryOnProviderError('rate_limited', 'Gemini is rate limiting requests. Try again shortly.', true);
  }
  if (response.status === 401 || response.status === 403) {
    return new TryOnProviderError('not_configured', 'Gemini rejected the API key.');
  }
  if (response.status === 400) {
    return new TryOnProviderError('invalid_request', `Gemini rejected the request: ${message}`);
  }
  return new TryOnProviderError('provider_error', `Gemini error ${response.status}: ${message}`, true);
}

function extractMessage(body: string): string | undefined {
  try {
    const parsed = JSON.parse(body) as { error?: { message?: string } };
    return parsed.error?.message;
  } catch {
    return body.slice(0, 200) || undefined;
  }
}

interface GeminiResponse {
  candidates?: Array<{
    finishReason?: string;
    content?: { parts?: Array<{ inlineData?: { data: string; mimeType?: string } }> };
  }>;
  promptFeedback?: { blockReason?: string };
}
