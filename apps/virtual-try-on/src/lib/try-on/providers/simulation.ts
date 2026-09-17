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
import type { GarmentLayer, TryOnCapabilities } from '../types';

/**
 * Offline fallback used when no AI provider is configured.
 *
 * It does NOT generate anything. It lays the flat product artwork over the
 * photo at anatomically-plausible anchor points so the flow can be demonstrated
 * end to end. Every result it produces is flagged `simulated: true` and carries
 * a burnt-in label, so a composite can never be mistaken for a real try-on —
 * including after it is downloaded or shared.
 */

/**
 * Where each layer sits, as a fraction of the subject frame.
 *
 * Calibrated against the studio figure, whose shoulders, hips and feet are at
 * known heights. An uploaded photo is framed however the shopper took it, so
 * these are an approximation — which is exactly why every result this provider
 * returns is labelled a preview rather than a try-on.
 */
const ANCHORS: Record<GarmentLayer, { cx: number; cy: number; width: number; opacity: number }> = {
  head: { cx: 0.5, cy: 0.15, width: 0.35, opacity: 0.96 },
  base: { cx: 0.5, cy: 0.381, width: 0.52, opacity: 0.9 },
  mid: { cx: 0.5, cy: 0.39, width: 0.56, opacity: 0.93 },
  outer: { cx: 0.5, cy: 0.4, width: 0.62, opacity: 0.96 },
  bottom: { cx: 0.5, cy: 0.656, width: 0.8, opacity: 0.93 },
  feet: { cx: 0.5, cy: 0.87, width: 0.34, opacity: 0.96 },
};

const LAYER_ORDER: GarmentLayer[] = ['feet', 'bottom', 'base', 'mid', 'outer', 'head'];

export class SimulationTryOnProvider implements VirtualTryOnProvider {
  readonly id = 'simulation';
  readonly label = 'Local preview (no AI)';
  readonly simulated = true;

  readonly capabilities: TryOnCapabilities = {
    maxGarments: 6,
    preservesBackground: true,
    timeoutMs: 30_000,
    acceptedMimeTypes: ['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml'],
    maxSubjectBytes: 12 * 1024 * 1024,
  };

  configuration(): ProviderConfiguration {
    return {
      configured: true,
      missing: [],
      notice:
        'No AI provider is configured, so results are locally composited previews — not AI try-ons.',
    };
  }

  async uploadImage(image: InlineImage): Promise<ProviderAsset> {
    return { kind: 'inline', image };
  }

  async startJob(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<ProviderJobRef> {
    const svg = composite(request);
    ctx.report(0.5, 'Laying the pieces out');
    return {
      id: `sim_${Math.random().toString(36).slice(2)}`,
      meta: { svg, readyAt: Date.now() + 1400 },
    };
  }

  async pollJob(ref: ProviderJobRef): Promise<ProviderJobUpdate> {
    const meta = (ref.meta ?? {}) as { svg?: string; readyAt?: number };
    if (!meta.svg) {
      return {
        status: 'failed',
        error: { code: 'provider_error', message: 'The preview was lost.', retryable: true },
      };
    }
    // A short, deliberate pause: the UI's loading state is part of what this
    // fallback exists to demonstrate.
    if (Date.now() < (meta.readyAt ?? 0)) {
      return { status: 'running', progress: 0.7, stage: 'Composing the preview' };
    }
    return {
      status: 'succeeded',
      progress: 1,
      stage: 'Finishing',
      image: {
        bytes: new TextEncoder().encode(meta.svg),
        mimeType: 'image/svg+xml',
        filename: 'try-on-preview.svg',
      },
      note: 'Locally composited preview — configure an AI provider for a real try-on.',
    };
  }

  async cancelJob(): Promise<void> {
    /* nothing in flight */
  }
}

function composite(request: PreparedTryOnRequest): string {
  const subject = request.subject;
  if (subject.kind !== 'inline') {
    throw new TryOnProviderError('provider_error', 'The preview needs the photo inline.');
  }

  const { width, height } = measure(subject.image);

  const ordered = [...request.garments].sort(
    (a, b) => LAYER_ORDER.indexOf(a.garment.layer) - LAYER_ORDER.indexOf(b.garment.layer),
  );

  const layers = ordered
    .map((entry, index) => {
      const anchor = ANCHORS[entry.garment.layer] ?? ANCHORS.outer;
      const w = width * anchor.width;
      const h = w * 1.25;
      const x = width * anchor.cx - w / 2;
      const y = height * anchor.cy - h / 2;
      return `<g opacity="${anchor.opacity}" transform="translate(${round(x)} ${round(y)})">
        ${renderAsset(entry.asset, w, h, `p${index}`)}
      </g>`;
    })
    .join('\n');


  const badgeWidth = Math.max(240, width * 0.34);
  const badgeHeight = badgeWidth * 0.17;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
  ${renderAsset(subject, width, height, 'sub', 'slice')}
  ${layers}
  <g transform="translate(${round(width - badgeWidth - width * 0.03)} ${round(height - badgeHeight - width * 0.03)})">
    <rect width="${round(badgeWidth)}" height="${round(badgeHeight)}" rx="${round(badgeHeight / 2)}" fill="#0b0b0d" fill-opacity="0.82"/>
    <text x="${round(badgeWidth / 2)}" y="${round(badgeHeight * 0.64)}" text-anchor="middle"
      font-family="ui-sans-serif, system-ui, sans-serif" font-size="${round(badgeHeight * 0.4)}"
      letter-spacing="${round(badgeHeight * 0.06)}" fill="#c7a57b">SIMULATED PREVIEW</text>
  </g>
</svg>`;
}

/**
 * Inline SVG artwork is embedded as markup rather than a nested data URI, and
 * its ids are namespaced so gradients and filters from different garments
 * cannot collide.
 *
 * Raster artwork is placed at an explicitly computed rect. An SVG rendered as
 * an image cannot always resolve a data URI's intrinsic size, and when it
 * cannot, `preserveAspectRatio` has nothing to work from and the image
 * collapses — so the fit is measured here instead of being left to the
 * renderer.
 */
function renderAsset(
  asset: ProviderAsset,
  width: number,
  height: number,
  prefix: string,
  fit: 'meet' | 'slice' = 'meet',
): string {
  if (asset.kind !== 'inline') {
    return `<image href="${asset.url}" x="0" y="0" width="${round(width)}" height="${round(height)}" preserveAspectRatio="xMidYMid ${fit}"/>`;
  }

  // An `<image>` element cannot reference another SVG document, so vector
  // artwork is spliced in as a nested `<svg>` instead.
  if (asset.image.mimeType === 'image/svg+xml') {
    const markup = new TextDecoder().decode(asset.image.bytes);
    const viewBox = /viewBox="([^"]+)"/.exec(markup)?.[1] ?? '0 0 800 1000';
    const inner = namespaceIds(stripRoot(markup), prefix);
    return `<svg x="0" y="0" viewBox="${viewBox}" width="${round(width)}" height="${round(height)}" preserveAspectRatio="xMidYMid ${fit}" overflow="${fit === 'slice' ? 'hidden' : 'visible'}">${inner}</svg>`;
  }

  const intrinsic = measure(asset.image);
  const scale =
    fit === 'slice'
      ? Math.max(width / intrinsic.width, height / intrinsic.height)
      : Math.min(width / intrinsic.width, height / intrinsic.height);
  const w = intrinsic.width * scale;
  const h = intrinsic.height * scale;
  return `<image href="${dataUri(asset.image)}" x="${round((width - w) / 2)}" y="${round((height - h) / 2)}" width="${round(w)}" height="${round(h)}" preserveAspectRatio="none"/>`;
}

function stripRoot(markup: string): string {
  return markup
    .replace(/^[\s\S]*?<svg[^>]*>/i, '')
    .replace(/<\/svg>\s*$/i, '')
    .trim();
}

function namespaceIds(markup: string, prefix: string): string {
  return markup
    .replace(/id="([^"]+)"/g, (_match, id: string) => `id="${prefix}-${id}"`)
    .replace(/url\(#([^)]+)\)/g, (_match, id: string) => `url(#${prefix}-${id})`)
    .replace(/(clip-path|filter|mask)="#([^"]+)"/g, (_m, attr: string, id: string) => `${attr}="#${prefix}-${id}"`);
}

function dataUri(image: InlineImage): string {
  return `data:${image.mimeType};base64,${Buffer.from(image.bytes).toString('base64')}`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Reads intrinsic dimensions without an image decoder: PNG and JPEG headers are
 * parsed directly, SVG falls back to its viewBox, and anything unrecognised
 * gets a sensible portrait frame.
 */
function measure(image: InlineImage): { width: number; height: number } {
  const fallback = { width: 900, height: 1200 };
  const bytes = image.bytes;

  if (image.mimeType === 'image/svg+xml') {
    const markup = new TextDecoder().decode(bytes.subarray(0, 2048));
    const viewBox = /viewBox="\s*[\d.-]+\s+[\d.-]+\s+([\d.]+)\s+([\d.]+)/.exec(markup);
    if (viewBox) return { width: Number(viewBox[1]), height: Number(viewBox[2]) };
    return fallback;
  }

  // PNG: IHDR width/height are big-endian uint32 at bytes 16..24.
  if (bytes.length > 24 && bytes[0] === 0x89 && bytes[1] === 0x50) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return { width: view.getUint32(16), height: view.getUint32(20) };
  }

  // JPEG: walk the segment markers to the first SOF frame header.
  if (bytes.length > 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let offset = 2;
    while (offset + 9 < bytes.length) {
      if (view.getUint8(offset) !== 0xff) {
        offset += 1;
        continue;
      }
      const marker = view.getUint8(offset + 1);
      const length = view.getUint16(offset + 2);
      const isFrameHeader = marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker);
      if (isFrameHeader) {
        return { width: view.getUint16(offset + 7), height: view.getUint16(offset + 5) };
      }
      offset += 2 + length;
    }
  }

  return fallback;
}
