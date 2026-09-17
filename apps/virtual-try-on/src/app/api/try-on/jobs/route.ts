import { createJob } from '@/lib/try-on/job-store';
import { getProvider } from '@/lib/try-on/registry';
import { ValidationError, parseTryOnRequest } from '@/lib/try-on/validate';

/** Roughly the largest body a downscaled photo plus garment artwork produces. */
const MAX_BODY_BYTES = 20 * 1024 * 1024;

/**
 * Starts a try-on. Returns immediately with a job the client polls — a model
 * call can take a minute, which is far too long to hold a request open.
 *
 * Nothing reaches the provider until this route is called, and it is only
 * called from an explicit "Generate" click in the fitting room.
 */
export async function POST(request: Request) {
  const declared = Number(request.headers.get('content-length') ?? 0);
  if (declared > MAX_BODY_BYTES) {
    return Response.json(
      { error: { code: 'invalid_request', message: 'That request is too large.' } },
      { status: 413 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { error: { code: 'invalid_request', message: 'Expected JSON.' } },
      { status: 400 },
    );
  }

  const provider = getProvider();

  try {
    const parsed = parseTryOnRequest(body, provider.capabilities);
    const job = createJob(parsed);
    return Response.json(job, { status: 202, headers: { 'cache-control': 'no-store' } });
  } catch (cause) {
    if (cause instanceof ValidationError) {
      return Response.json(
        { error: { code: 'invalid_request', message: cause.message, field: cause.field } },
        { status: 422 },
      );
    }
    const message = cause instanceof Error ? cause.message : 'Could not start the try-on.';
    return Response.json({ error: { code: 'unknown', message } }, { status: 500 });
  }
}
