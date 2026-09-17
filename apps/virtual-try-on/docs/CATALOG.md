# Catalogue and artwork

## What ships

`public/demo/` holds the demo catalogue: fourteen garments and one studio
figure, drawn as SVG by `scripts/generate-assets.mjs`. They are original
illustrations, generated locally, committed to the repository — there are no
external image URLs anywhere in this module, so nothing goes missing when a
third-party host changes.

```
npm run assets
```

reads `scripts/lib/manifest.mjs` and writes:

```
public/demo/garments/<id>.svg          flat-lay product artwork
public/demo/models/studio-figure.svg   the default fitting-room figure
src/data/catalog.generated.json        the catalogue the app consumes
```

The manifest is the single source of truth; the generator derives both the
artwork and the data from it, so they cannot drift apart.

## Replacing it with real photography

Two independent changes.

**The images.** Drop the client's product shots into `public/` and point each
product's `image` at them. Cut-outs on a plain ground work best: the product
card renders the image with `object-contain` on a dark surface, and every
try-on provider was trained on studio flat-lays. JPEG, PNG or WebP.

Vector artwork is a demo convenience, not a requirement. Image models reject
SVG, so `src/lib/image-client.ts` rasterises it in the browser before sending;
with raster artwork that step is skipped entirely.

**The data.** `src/data/catalog.ts` is the seam. It currently reads the
generated JSON, but nothing downstream cares where products come from — replace
its body with a fetch against Shopify, commercetools or a bespoke API and keep
the `Product` shape:

| Field | Notes |
| --- | --- |
| `id`, `name`, `category` | `category` must match an entry in `CATEGORIES` |
| `price`, `compareAtPrice?` | Minor units are not used; format via `lib/format.ts` |
| `image` | App-relative path or absolute URL |
| `layer` | `feet` · `bottom` · `base` · `mid` · `outer` · `head` |
| `layerRank` | Sort order within the outfit; higher sits on top |
| `colors`, `sizes` | Drive the quick-view selectors |
| `rating`, `reviews`, `fabric`, `care`, `description`, `badge?` | Presentation |

`layer` and `layerRank` are the only fields a typical PIM will not already have.
They decide what goes over what, and they stop the fitting room putting two
coats on one person.

## The generator, if you want to extend it

`scripts/lib/` is a small parametric drawing system:

- `draw.mjs` — silhouette primitives (`halfTorso`, `sleeve`, `halfTrouser`),
  gradients, fabric texture, topstitching. Garments are symmetric, so only the
  right half is described and then mirrored.
- `garments.mjs` — one entry per shape. Each is the shared `topGarment` builder
  with different silhouette parameters plus its own trim.
- `model.mjs` — the studio figure, deliberately featureless so it reads as a
  stand-in rather than a depiction of a person.
- `manifest.mjs` — categories, layer ranks, colour palettes, products.

Two constraints worth knowing if you edit the drawing code, because both fail
silently:

- A `<clipPath>` may only contain shape elements. Put the mirror transform on
  the `<path>` (`mirroredPath`) — a `<g>` inside a clipPath is ignored and
  empties the clip region.
- A filter that generates its own output, such as `feTurbulence`, fills the
  whole filter region unless it is composited back against `SourceGraphic`.
  Without that you get a rectangle behind the garment.
