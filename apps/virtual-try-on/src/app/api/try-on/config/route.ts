import { describeProvider } from '@/lib/try-on/registry';

/**
 * Tells the storefront which provider is active and what it can do, so the
 * fitting room can set its own limits and label simulated output honestly.
 */
export async function GET() {
  return Response.json(describeProvider(), {
    headers: { 'cache-control': 'no-store' },
  });
}
