import 'server-only';

import type { VirtualTryOnProvider } from './provider';
import { GeminiTryOnProvider } from './providers/gemini';
import { ReplicateTryOnProvider } from './providers/replicate';
import { SimulationTryOnProvider } from './providers/simulation';
import type { TryOnProviderInfo } from './types';

const factories: Record<string, () => VirtualTryOnProvider> = {
  gemini: () => new GeminiTryOnProvider(),
  replicate: () => new ReplicateTryOnProvider(),
  simulation: () => new SimulationTryOnProvider(),
};

export const PROVIDER_IDS = Object.keys(factories);

let cached: VirtualTryOnProvider | undefined;
let cachedFor: string | undefined;

/**
 * Resolves the active provider from `TRYON_PROVIDER`.
 *
 * When the named provider is present but unconfigured we still return it, so
 * the UI can say exactly which environment variables are missing instead of
 * silently degrading to the local preview. Falling back only happens when
 * nothing is named at all.
 */
export function getProvider(): VirtualTryOnProvider {
  const requested = (process.env.TRYON_PROVIDER || '').trim().toLowerCase();
  const id = requested in factories ? requested : 'simulation';

  if (cached && cachedFor === id) return cached;
  cached = factories[id]();
  cachedFor = id;
  return cached;
}

export function describeProvider(): TryOnProviderInfo {
  const provider = getProvider();
  const config = provider.configuration();
  return {
    id: provider.id,
    label: provider.label,
    configured: config.configured,
    simulated: provider.simulated,
    missing: config.missing,
    capabilities: provider.capabilities,
    notice: config.notice,
  };
}
