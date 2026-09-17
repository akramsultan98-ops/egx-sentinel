import type { GarmentLayer, TryOnCapabilities, TryOnGarment, TryOnRequest } from './types';

/**
 * Request validation shared by the route handler and the browser, so the client
 * can fail fast with the same rules the server enforces.
 */

export const LAYERS: GarmentLayer[] = ['feet', 'bottom', 'base', 'mid', 'outer', 'head'];

export const ACCEPTED_UPLOAD_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic'];

/** Raw upload ceiling, before the browser downscales. */
export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

/** Longest edge the browser downscales an upload to before it is sent. */
export const UPLOAD_MAX_EDGE = 1280;

export const MIN_UPLOAD_EDGE = 256;

/** Ceiling for a garment image sent inline as a data URL (~6MB decoded). */
export const MAX_GARMENT_URL_CHARS = 8 * 1024 * 1024;

export class ValidationError extends Error {
  readonly field: string;
  constructor(field: string, message: string) {
    super(message);
    this.name = 'ValidationError';
    this.field = field;
  }
}

const DATA_URL_PREFIX = /^data:(image\/[a-z+.-]+);base64,/;

export function parseTryOnRequest(body: unknown, capabilities: TryOnCapabilities): TryOnRequest {
  if (!isRecord(body)) throw new ValidationError('body', 'Expected a JSON object.');

  const subject = body.subject;
  if (!isRecord(subject)) throw new ValidationError('subject', 'A photo is required.');

  const kind = subject.kind;
  if (kind !== 'upload' && kind !== 'demo-model') {
    throw new ValidationError('subject.kind', 'Unknown photo source.');
  }

  const dataUrl = subject.dataUrl;
  if (typeof dataUrl !== 'string') {
    throw new ValidationError('subject.dataUrl', 'The photo is missing.');
  }

  const match = DATA_URL_PREFIX.exec(dataUrl);
  if (!match) {
    throw new ValidationError('subject.dataUrl', 'The photo must be a base64 image data URL.');
  }

  const mimeType = match[1];
  if (!capabilities.acceptedMimeTypes.includes(mimeType)) {
    throw new ValidationError(
      'subject.dataUrl',
      `${mimeType} is not supported by this provider. Use ${capabilities.acceptedMimeTypes.join(', ')}.`,
    );
  }

  const approximateBytes = Math.floor((dataUrl.length - match[0].length) * 0.75);
  if (approximateBytes > capabilities.maxSubjectBytes) {
    throw new ValidationError(
      'subject.dataUrl',
      `That photo is too large (limit ${formatBytes(capabilities.maxSubjectBytes)}).`,
    );
  }

  const width = toPositiveInt(subject.width);
  const height = toPositiveInt(subject.height);
  if (!width || !height) {
    throw new ValidationError('subject', 'The photo dimensions are missing.');
  }
  if (Math.max(width, height) < MIN_UPLOAD_EDGE) {
    throw new ValidationError(
      'subject',
      `That photo is too small — use one at least ${MIN_UPLOAD_EDGE}px on its longest side.`,
    );
  }

  const rawGarments = body.garments;
  if (!Array.isArray(rawGarments) || rawGarments.length === 0) {
    throw new ValidationError('garments', 'Add at least one piece to try on.');
  }
  if (rawGarments.length > capabilities.maxGarments) {
    throw new ValidationError(
      'garments',
      `This provider fits up to ${capabilities.maxGarments} pieces at a time.`,
    );
  }

  const garments = rawGarments.map((raw, index) => parseGarment(raw, index));

  const notes = typeof body.notes === 'string' ? body.notes.slice(0, 400) : undefined;

  return { subject: { kind, dataUrl, width, height }, garments, notes };
}

function parseGarment(raw: unknown, index: number): TryOnGarment {
  const at = `garments[${index}]`;
  if (!isRecord(raw)) throw new ValidationError(at, 'Malformed garment.');

  const productId = asString(raw.productId, `${at}.productId`);
  const name = asString(raw.name, `${at}.name`);
  const category = asString(raw.category, `${at}.category`);

  // Not `asString`: garment artwork arrives as a data URL, which is megabytes
  // long. Truncating it to the short-field limit would silently corrupt the
  // image rather than fail.
  if (typeof raw.imageUrl !== 'string' || !raw.imageUrl.trim()) {
    throw new ValidationError(`${at}.imageUrl`, 'This field is required.');
  }
  const imageUrl = raw.imageUrl;
  if (imageUrl.length > MAX_GARMENT_URL_CHARS) {
    throw new ValidationError(`${at}.imageUrl`, 'That product image is too large to send.');
  }

  const layer = raw.layer;
  if (typeof layer !== 'string' || !LAYERS.includes(layer as GarmentLayer)) {
    throw new ValidationError(`${at}.layer`, 'Unknown garment layer.');
  }

  // Garment artwork may only come from this app's own catalogue or from a data
  // URL the browser rasterised — never an arbitrary URL, which would turn this
  // route into a server-side request forgery vector.
  const isLocal = imageUrl.startsWith('/') && !imageUrl.startsWith('//');
  const isInline = imageUrl.startsWith('data:image/');
  if (!isLocal && !isInline) {
    throw new ValidationError(`${at}.imageUrl`, 'Garment images must come from this catalogue.');
  }
  if (isLocal && imageUrl.includes('..')) {
    throw new ValidationError(`${at}.imageUrl`, 'Invalid garment image path.');
  }

  return {
    productId,
    name,
    category,
    imageUrl,
    layer: layer as GarmentLayer,
    colorLabel: typeof raw.colorLabel === 'string' ? raw.colorLabel.slice(0, 60) : undefined,
    size: typeof raw.size === 'string' ? raw.size.slice(0, 20) : undefined,
  };
}

/** For short descriptive fields only — it truncates, so never use it for URLs. */
function asString(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new ValidationError(field, 'This field is required.');
  }
  return value.slice(0, 200);
}

function toPositiveInt(value: unknown): number | undefined {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / (1024 * 1024))}MB`;
  return `${Math.round(bytes / 1024)}KB`;
}
