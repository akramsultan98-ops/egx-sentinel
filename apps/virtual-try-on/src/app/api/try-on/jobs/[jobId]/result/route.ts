import { readResult } from '@/lib/try-on/job-store';

/**
 * Streams the rendered image.
 *
 * Results are served from here rather than inlined into the job JSON so the
 * browser can cache them, `<img>` can stream them, and download/share get a
 * real URL instead of a multi-megabyte data URL.
 */
export async function GET(_request: Request, ctx: RouteContext<'/api/try-on/jobs/[jobId]/result'>) {
  const { jobId } = await ctx.params;
  const image = readResult(jobId);

  if (!image) {
    return new Response('Not found', { status: 404 });
  }

  return new Response(new Uint8Array(image.bytes) as unknown as BodyInit, {
    headers: {
      'content-type': image.mimeType,
      'content-length': String(image.bytes.byteLength),
      'content-disposition': `inline; filename="${image.filename}"`,
      // Private: a result belongs to one shopper's session, never a shared cache.
      'cache-control': 'private, max-age=600',
      'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    },
  });
}
