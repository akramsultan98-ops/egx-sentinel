# Virtual Try-On

A reusable AI fitting room for fashion e-commerce, shipped with a working
storefront around it so it can be demonstrated, sold and deployed as a unit.

A shopper browses the catalogue, taps the hanger on any product, uploads a
photo, and gets a rendering of themselves in the piece — then layers another
garment on top, compares it against the original photo, and adds it to the bag.

```
npm install
npm run assets     # renders the demo catalogue artwork (already committed)
npm run dev        # http://localhost:3000
```

Out of the box it runs on the local preview provider, which composites product
artwork over the photo and never claims to be AI. Add a `GEMINI_API_KEY` and set
`TRYON_PROVIDER=gemini` for real generation. See [`.env.example`](.env.example).

## Stack

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · npm.
No database, no auth, no external image hosting — the module is self-contained
and drops into an existing storefront without bringing infrastructure with it.

## How it fits together

```
Storefront (client)                Route handlers (server)        Provider
────────────────────               ───────────────────────        ────────
ProductCard  ─ hanger ─┐
                       ├─> FittingRoomProvider
PhotoUploader ─────────┘     │
  validate + downscale       │  POST /api/try-on/jobs ──> createJob()
  in the browser             │        (explicit click)       │
                             │                               ├─> uploadImage()
                             │  GET  /api/try-on/jobs/:id <──┤   startJob()
                             │        (poll ~1s)             │   pollJob()
                             │                               │   cancelJob()
                             └─ LookViewer <── GET …/result ─┘
                                compare · download · share
```

Four things follow from that shape:

- **Credentials stay on the server.** The browser only ever talks to this app.
- **Generation is a job, not a request.** A model call can take a minute, which
  is far too long to hold an HTTP request open. The client polls.
- **The provider is swappable.** Everything above the adapter is provider
  agnostic; see [`docs/PROVIDERS.md`](docs/PROVIDERS.md).
- **Nothing is sent without a click.** The photo is read, validated and
  downscaled locally; it leaves the device only when the shopper presses
  Generate, and the first time they do they are told exactly where it goes.

## Source map

| Path | What lives there |
| --- | --- |
| `src/lib/try-on/types.ts` | Domain types shared by client, server and adapters |
| `src/lib/try-on/provider.ts` | `VirtualTryOnProvider` contract + the lifecycle runner |
| `src/lib/try-on/providers/` | Gemini, Replicate and local-preview adapters |
| `src/lib/try-on/registry.ts` | Resolves the active provider from `TRYON_PROVIDER` |
| `src/lib/try-on/job-store.ts` | In-process job store with a TTL |
| `src/lib/try-on/validate.ts` | Request validation, shared by both sides |
| `src/lib/image-client.ts` | Browser-side decode, downscale, rasterise |
| `src/app/api/try-on/` | `config`, `jobs`, `jobs/:id`, `jobs/:id/result` |
| `src/components/fitting-room/` | The fitting room, uploader, compare slider, viewer |
| `src/components/store/` | Header, filters, grid, card, quick view, bag |
| `src/state/` | Storefront and fitting-room state |
| `src/data/catalog.ts` | The product model — point this at a real commerce API |
| `scripts/` | Demo artwork generator — see [`docs/CATALOG.md`](docs/CATALOG.md) |

## Embedding into an existing storefront

The fitting room does not depend on this demo storefront. To drop it into a
host application:

1. Copy `src/lib/try-on/`, `src/lib/image-client.ts`,
   `src/components/fitting-room/`, `src/components/ui/`,
   `src/state/fitting-room-context.tsx` and `src/app/api/try-on/`.
2. Wrap the shopping surface in `<FittingRoomProvider catalog={products}>`.
   `catalog` needs `id`, `name`, `category`, `image`, `layer`, `layerRank`,
   `colors` and `sizes` per product — map the host's own product type onto
   `src/data/catalog.ts`'s `Product`.
3. Render `<FittingRoomPanel />` once, near the root of that surface.
4. Call `togglePick(product)` from your own "Try on" control.
5. Replace `useStore().addToBag` in `FittingRoomPanel` with the host's cart.

`layer` (`feet` · `bottom` · `base` · `mid` · `outer` · `head`) is the only
concept the host catalogue has to supply that a normal PIM does not. It drives
layering order and stops two coats being worn at once.

## Design system

One dark palette, one accent, defined as tokens in `src/app/globals.css`.
Components read tokens rather than literal colours, so re-skinning for a brand
is an edit to that one `@theme` block. The storefront name, currency and locale
come from `NEXT_PUBLIC_STORE_*`.

## Production notes

Things to decide before a client deployment:

- **Job store.** `job-store.ts` is an in-process `Map` with a 15-minute TTL,
  which is correct for one instance and wrong behind a load balancer. Swap it
  for Redis or a table; the routes only use `create` / `get` / `cancel` /
  `readResult`.
- **Rate limiting.** `POST /api/try-on/jobs` is unauthenticated and spends
  provider credits. Put it behind the host's auth, a per-session quota, or both.
- **Result retention.** Results live in memory and expire with the job. If
  shoppers should keep their looks, persist them and revisit the `private`
  cache-control on the result route.
- **Photo handling.** Uploads are held only for the life of the job and are
  never written to disk by this module. The provider's own retention is the
  provider's; the consent dialog names them so the shopper can check.
- **Demo artwork.** `public/demo/` is illustrated placeholder artwork. Replace
  it with the client's photography — see [`docs/CATALOG.md`](docs/CATALOG.md).

## Checks

```
npm run typecheck
npm run lint
npm run build
npm run check      # all three
```
