'use client';

import {
  ACCEPTED_UPLOAD_TYPES,
  MAX_UPLOAD_BYTES,
  MIN_UPLOAD_EDGE,
  UPLOAD_MAX_EDGE,
  ValidationError,
  formatBytes,
} from '@/lib/try-on/validate';

/**
 * Browser-side image work.
 *
 * Photos are validated and downscaled here, before anything leaves the device:
 * a 12MP phone photo becomes a ~300KB upload, which is faster, cheaper at the
 * provider, and well within every model's input limits.
 */

export interface PreparedImage {
  dataUrl: string;
  width: number;
  height: number;
  /** Bytes after downscaling, for display. */
  bytes: number;
  sourceName: string;
}

export async function prepareUpload(file: File): Promise<PreparedImage> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new ValidationError('file', `That file is ${formatBytes(file.size)} — the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`);
  }

  const type = file.type.toLowerCase();
  if (type && !ACCEPTED_UPLOAD_TYPES.includes(type)) {
    throw new ValidationError('file', 'Use a JPEG, PNG or WebP photo.');
  }

  const bitmap = await decode(file);

  try {
    if (Math.max(bitmap.width, bitmap.height) < MIN_UPLOAD_EDGE) {
      throw new ValidationError(
        'file',
        `That photo is only ${bitmap.width}×${bitmap.height}. Use one at least ${MIN_UPLOAD_EDGE}px on its longest side.`,
      );
    }

    const scale = Math.min(1, UPLOAD_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.round(bitmap.width * scale);
    const height = Math.round(bitmap.height * scale);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) throw new ValidationError('file', 'This browser could not read the photo.');

    context.imageSmoothingQuality = 'high';
    context.drawImage(bitmap, 0, 0, width, height);

    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    return {
      dataUrl,
      width,
      height,
      bytes: Math.floor((dataUrl.length - dataUrl.indexOf(',') - 1) * 0.75),
      sourceName: file.name || 'photo.jpg',
    };
  } finally {
    if ('close' in bitmap) bitmap.close();
  }
}

/**
 * Fetches catalogue artwork as a data URL without converting it.
 *
 * Used when the active provider accepts SVG — going through a canvas would
 * throw away the vector artwork for nothing.
 */
export async function inlineAsset(url: string): Promise<string> {
  if (url.startsWith('data:')) return url;
  const response = await fetch(url);
  if (!response.ok) {
    throw new ValidationError('garment', 'That product image could not be loaded.');
  }
  const blob = await response.blob();
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new ValidationError('garment', 'That product image could not be read.'));
    reader.readAsDataURL(blob);
  });
}

/**
 * Rasterises catalogue artwork to PNG.
 *
 * The demo catalogue ships as SVG, which no image model accepts, so garments
 * are converted here rather than shipping a server-side rasteriser.
 */
export async function rasterizeGarment(url: string, edge = 768): Promise<string> {
  if (url.startsWith('data:image/png') || url.startsWith('data:image/jpeg')) return url;

  const image = await loadImage(url);
  const ratio = image.naturalWidth && image.naturalHeight ? image.naturalWidth / image.naturalHeight : 0.8;
  const width = ratio >= 1 ? edge : Math.round(edge * ratio);
  const height = ratio >= 1 ? Math.round(edge / ratio) : edge;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new ValidationError('garment', 'This browser could not read the product image.');

  // A white ground keeps the cut-out readable to models trained on studio shots.
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);

  return canvas.toDataURL('image/png');
}

async function decode(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    try {
      // `imageOrientation` applies the EXIF rotation phones record, so portrait
      // photos do not arrive at the provider lying on their side.
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      /* fall through to the <img> path */
    }
  }

  const url = URL.createObjectURL(file);
  try {
    return await loadImage(url);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = () =>
      reject(new ValidationError('file', 'That image could not be loaded. It may be corrupt.'));
    image.src = src;
  });
}
