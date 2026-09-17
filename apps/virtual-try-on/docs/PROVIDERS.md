# Try-on providers

The fitting room talks to one `VirtualTryOnProvider`. Which one is decided by
`TRYON_PROVIDER` at startup and never by the browser.

## The contract

```ts
interface VirtualTryOnProvider {
  readonly id: string;
  readonly label: string;
  readonly simulated: boolean;
  readonly capabilities: TryOnCapabilities;

  configuration(): ProviderConfiguration;
  uploadImage(image: InlineImage, ctx: ProviderContext): Promise<ProviderAsset>;
  startJob(request: PreparedTryOnRequest, ctx: ProviderContext): Promise<ProviderJobRef>;
  pollJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<ProviderJobUpdate>;
  cancelJob(ref: ProviderJobRef, ctx: ProviderContext): Promise<void>;
}
```

`executeTryOn()` in `src/lib/try-on/provider.ts` drives all four: it uploads
every image, starts the job, polls with backoff until the job reaches a terminal
state or the capability timeout expires, and converts failures into a
`TryOnError`. Retry, backoff and timeout policy therefore live in one place and
behave identically across backends — an adapter only has to describe its own
service.

`capabilities` is served to the browser by `GET /api/try-on/config`, and the UI
uses it: `maxGarments` caps how many pieces can be layered, `acceptedMimeTypes`
decides whether catalogue artwork is sent as vector or rasterised to PNG first,
and `maxSubjectBytes` bounds the upload.

## Shipped adapters

### `gemini`

Google's image model, called over the REST API with the photo and the product
shots inline. Gemini answers one request rather than exposing a queue, so
`startJob` fires the request and parks the promise while `pollJob` reports on
it — the storefront's polling contract stays the same either way. Progress is
interpolated, because the API reports none.

```
TRYON_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image   # optional
```

Layering is native: all garments go into a single prompt, ordered.

### `replicate`

For hosted try-on models (IDM-VTON, CatVTON and similar). Replicate has a real
prediction queue, which is the shape this interface was designed around.

```
TRYON_PROVIDER=replicate
REPLICATE_API_TOKEN=...
REPLICATE_TRYON_MODEL=owner/name          # or owner/name:version
REPLICATE_TRYON_INPUT_MAP={"person":"human_img","garment":"garm_img","description":"garment_des"}
```

The model is not hard-coded, and `REPLICATE_TRYON_INPUT_MAP` maps this module's
three inputs onto whatever the chosen model calls them. These models take one
garment per prediction, so `pollJob` chains them: each finished render becomes
the person input for the next layer.

### `simulation`

The fallback when nothing is configured. It performs no generation — it places
the flat product artwork over the photo at anatomically-plausible anchor points
so the flow can be shown end to end, offline, with no credentials.

Every result it returns is marked `simulated: true`, which the panel and the
result viewer both surface, and the image itself carries a burnt-in
`SIMULATED PREVIEW` badge so a downloaded or shared file stays honest about
what it is.

## Adding one

1. Implement the interface in `src/lib/try-on/providers/<name>.ts`.
2. Register it in the `factories` map in `src/lib/try-on/registry.ts`.
3. Report missing environment variables from `configuration()` — the UI shows
   them by name rather than silently degrading.
4. Throw `TryOnProviderError` with the closest `TryOnErrorCode`. Mark an error
   `retryable` only when sending the same request again could plausibly work;
   the fitting room offers a retry button on those and not on the rest.

Set `simulated: true` if the adapter does not run a real model. That flag is the
only thing standing between a demo composite and a claim the client cannot back
up.
