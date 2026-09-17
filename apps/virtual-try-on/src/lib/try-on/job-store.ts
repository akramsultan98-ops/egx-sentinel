import 'server-only';

import { executeTryOn, toTryOnError, type InlineImage } from './provider';
import { getProvider } from './registry';
import type { TryOnJob, TryOnRequest } from './types';

/**
 * In-process job store.
 *
 * Deliberately simple: try-on jobs are short-lived and their output is
 * disposable, so a bounded in-memory map with a TTL is the right amount of
 * machinery for a single deployment. Running more than one instance behind a
 * load balancer means swapping this file for Redis or a table — the interface
 * below (`create` / `get` / `cancel` / `readResult`) is all the routes use.
 */

const JOB_TTL_MS = 15 * 60 * 1000;
const MAX_JOBS = 200;
const SWEEP_INTERVAL_MS = 60 * 1000;

interface Entry {
  job: TryOnJob;
  image?: InlineImage;
  controller: AbortController;
  expiresAt: number;
}

// Survives dev-server hot reloads, which otherwise orphan in-flight jobs.
const globalRef = globalThis as typeof globalThis & {
  __tryOnJobs?: Map<string, Entry>;
  __tryOnSweep?: ReturnType<typeof setInterval>;
};

const jobs: Map<string, Entry> = (globalRef.__tryOnJobs ??= new Map());

if (!globalRef.__tryOnSweep) {
  globalRef.__tryOnSweep = setInterval(sweep, SWEEP_INTERVAL_MS);
  globalRef.__tryOnSweep.unref?.();
}

function sweep() {
  const now = Date.now();
  for (const [id, entry] of jobs) {
    if (entry.expiresAt < now) {
      entry.controller.abort();
      jobs.delete(id);
    }
  }
}

function evictOldest() {
  while (jobs.size >= MAX_JOBS) {
    const oldest = jobs.keys().next();
    if (oldest.done) break;
    jobs.get(oldest.value)?.controller.abort();
    jobs.delete(oldest.value);
  }
}

export function createJob(request: TryOnRequest): TryOnJob {
  evictOldest();

  const provider = getProvider();
  const id = `job_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const now = Date.now();

  const job: TryOnJob = {
    id,
    status: 'queued',
    provider: provider.id,
    providerLabel: provider.label,
    progress: 0.02,
    stage: 'Queued',
    createdAt: now,
    updatedAt: now,
    garmentIds: request.garments.map((garment) => garment.productId),
  };

  const entry: Entry = { job, controller: new AbortController(), expiresAt: now + JOB_TTL_MS };
  jobs.set(id, entry);

  // Run detached: the client polls GET /api/try-on/jobs/:id rather than holding
  // this request open for the length of a model call.
  void run(entry, request);

  return job;
}

async function run(entry: Entry, request: TryOnRequest) {
  const provider = getProvider();
  const { job } = entry;

  job.status = 'running';
  job.updatedAt = Date.now();

  try {
    const executed = await executeTryOn(provider, request, {
      signal: entry.controller.signal,
      report(progress, stage) {
        // Progress never goes backwards — a jumpy bar reads as broken.
        job.progress = Math.max(job.progress, Math.min(0.99, progress));
        job.stage = stage;
        job.updatedAt = Date.now();
      },
    });

    if (entry.controller.signal.aborted) return;

    entry.image = executed.image;
    job.status = 'succeeded';
    job.progress = 1;
    job.stage = 'Ready';
    job.updatedAt = Date.now();
    job.result = {
      imageUrl: `/api/try-on/jobs/${job.id}/result`,
      mimeType: executed.image.mimeType,
      simulated: provider.simulated,
      provider: provider.id,
      providerLabel: provider.label,
      latencyMs: executed.latencyMs,
      note: executed.note,
    };
  } catch (cause) {
    const error = toTryOnError(cause);
    job.status = error.code === 'cancelled' ? 'cancelled' : 'failed';
    job.error = error;
    job.stage = error.code === 'cancelled' ? 'Cancelled' : 'Failed';
    job.updatedAt = Date.now();
  }
}

export function getJob(id: string): TryOnJob | undefined {
  const entry = jobs.get(id);
  if (!entry) return undefined;
  entry.expiresAt = Date.now() + JOB_TTL_MS;
  return entry.job;
}

export function cancelJob(id: string): TryOnJob | undefined {
  const entry = jobs.get(id);
  if (!entry) return undefined;
  entry.controller.abort();
  if (entry.job.status === 'queued' || entry.job.status === 'running') {
    entry.job.status = 'cancelled';
    entry.job.stage = 'Cancelled';
    entry.job.updatedAt = Date.now();
  }
  return entry.job;
}

export function readResult(id: string): InlineImage | undefined {
  const entry = jobs.get(id);
  if (!entry?.image) return undefined;
  entry.expiresAt = Date.now() + JOB_TTL_MS;
  return entry.image;
}
