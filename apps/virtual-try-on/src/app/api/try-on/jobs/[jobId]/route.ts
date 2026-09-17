import { cancelJob, getJob } from '@/lib/try-on/job-store';

const NOT_FOUND = {
  error: { code: 'not_found', message: 'That try-on has expired. Generate a new one.' },
};

/** Poll target for an in-flight try-on. */
export async function GET(_request: Request, ctx: RouteContext<'/api/try-on/jobs/[jobId]'>) {
  const { jobId } = await ctx.params;
  const job = getJob(jobId);
  if (!job) return Response.json(NOT_FOUND, { status: 404 });
  return Response.json(job, { headers: { 'cache-control': 'no-store' } });
}

/** Abort an in-flight try-on; used by the panel's cancel action. */
export async function DELETE(_request: Request, ctx: RouteContext<'/api/try-on/jobs/[jobId]'>) {
  const { jobId } = await ctx.params;
  const job = cancelJob(jobId);
  if (!job) return Response.json(NOT_FOUND, { status: 404 });
  return Response.json(job, { headers: { 'cache-control': 'no-store' } });
}
