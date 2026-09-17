/**
 * Parametric garment drawing primitives.
 *
 * Everything is drawn inside an 800x1000 viewBox. Garments are symmetric, so we
 * only describe the right-hand half (x >= 400) and mirror it. Asymmetric details
 * (lapel overlap, zip pull, chest pocket) are layered on afterwards.
 *
 * These are original illustrations used as demo catalog imagery. A brand
 * deploying this module replaces the generated files with real photography —
 * see docs/CATALOG.md.
 */

export const W = 800;
export const H = 1000;
export const CX = W / 2;

const n = (v) => Math.round(v * 100) / 100;

/** Mirror a group of shapes across the vertical centre line. */
export function mirrored(inner) {
  return `<g>${inner}</g><g transform="matrix(-1 0 0 1 ${W} 0)">${inner}</g>`;
}

/**
 * Mirror a single path for use inside `<clipPath>`.
 *
 * A clipPath may only contain shape elements — a `<g>` in there is ignored,
 * silently emptying the clip region — so the mirror transform goes on the path.
 */
export function mirroredPath(d) {
  return `<path d="${d}"/><path transform="matrix(-1 0 0 1 ${W} 0)" d="${d}"/>`;
}

/**
 * Right half of a torso: neck -> shoulder -> armhole -> side seam -> hem.
 */
export function halfTorso({
  neckX = 44,
  neckDip = 250,
  shoulderY = 236,
  shoulderX = 152,
  shoulderDrop = 26,
  armpitX = 128,
  armpitY = 372,
  waistX = 132,
  waistY = 590,
  hemX = 140,
  hemY = 760,
  hemDip = 18,
}) {
  const nx = CX + neckX;
  const sx = CX + shoulderX;
  const ax = CX + armpitX;
  const wx = CX + waistX;
  const hx = CX + hemX;
  return [
    `M ${CX} ${n(neckDip)}`,
    `C ${n(CX + neckX * 0.55)} ${n(neckDip - 2)} ${n(nx - 8)} ${n(shoulderY + 8)} ${n(nx)} ${n(shoulderY)}`,
    `C ${n(nx + (sx - nx) * 0.45)} ${n(shoulderY - 6)} ${n(sx - 14)} ${n(shoulderY + shoulderDrop * 0.4)} ${n(sx)} ${n(shoulderY + shoulderDrop)}`,
    `C ${n(sx - 2)} ${n(shoulderY + shoulderDrop + 40)} ${n(ax + 10)} ${n(armpitY - 34)} ${n(ax)} ${n(armpitY)}`,
    `C ${n(ax - 4)} ${n(armpitY + 70)} ${n(wx + 4)} ${n(waistY - 80)} ${n(wx)} ${n(waistY)}`,
    `C ${n(wx - 2)} ${n(waistY + 60)} ${n(hx - 2)} ${n(hemY - 70)} ${n(hx)} ${n(hemY)}`,
    `C ${n(hx - 30)} ${n(hemY + hemDip)} ${n(CX + 40)} ${n(hemY + hemDip)} ${n(CX)} ${n(hemY + hemDip)}`,
    'Z',
  ].join(' ');
}

/**
 * Right sleeve. `length` is the cuff Y coordinate; `flare` widens the cuff.
 */
export function sleeve({
  shoulderY = 236,
  shoulderX = 152,
  shoulderDrop = 26,
  armpitX = 128,
  armpitY = 372,
  cuffY = 660,
  cuffOuter = 208,
  cuffInner = 150,
  bow = 26,
}) {
  const sx = CX + shoulderX;
  const ax = CX + armpitX;
  const ox = CX + cuffOuter;
  const ix = CX + cuffInner;
  return [
    `M ${n(sx - 4)} ${n(shoulderY + shoulderDrop - 4)}`,
    `C ${n(sx + 42)} ${n(shoulderY + shoulderDrop + 26)} ${n(ox + bow)} ${n(cuffY - 190)} ${n(ox)} ${n(cuffY)}`,
    `C ${n(ox - 8)} ${n(cuffY + 20)} ${n(ix + 6)} ${n(cuffY + 22)} ${n(ix)} ${n(cuffY)}`,
    `C ${n(ix - 10)} ${n(cuffY - 150)} ${n(ax - 6)} ${n(armpitY + 60)} ${n(ax - 2)} ${n(armpitY - 4)}`,
    'Z',
  ].join(' ');
}

/** Right half of a trouser leg pair. */
export function halfTrouser({
  waistY = 250,
  waistX = 128,
  hipX = 146,
  hipY = 390,
  kneeX = 96,
  kneeY = 620,
  hemX = 86,
  hemY = 880,
  inseamX = 16,
  crotchY = 470,
}) {
  const wx = CX + waistX;
  const px = CX + hipX;
  const kx = CX + kneeX;
  const hx = CX + hemX;
  const ix = CX + inseamX;
  return [
    `M ${CX} ${n(waistY)}`,
    `L ${n(wx)} ${n(waistY)}`,
    `C ${n(px)} ${n(waistY + 80)} ${n(px)} ${n(hipY)} ${n(kx + 24)} ${n(kneeY - 90)}`,
    `C ${n(kx + 6)} ${n(kneeY)} ${n(hx + 10)} ${n(hemY - 140)} ${n(hx)} ${n(hemY)}`,
    `L ${n(ix + 4)} ${n(hemY)}`,
    `C ${n(ix + 8)} ${n(hemY - 160)} ${n(ix + 10)} ${n(kneeY)} ${n(ix + 12)} ${n(crotchY)}`,
    `L ${CX} ${n(crotchY - 34)}`,
    'Z',
  ].join(' ');
}

/** Linear gradient tuned so the light reads as coming from the upper-left. */
export function fabricGradient(id, { light, base, dark }) {
  return `<linearGradient id="${id}" x1="0.12" y1="0.04" x2="0.92" y2="0.98">
      <stop offset="0" stop-color="${light}"/>
      <stop offset="0.42" stop-color="${base}"/>
      <stop offset="1" stop-color="${dark}"/>
    </linearGradient>`;
}

export function softShadow(id) {
  return `<filter id="${id}" x="-25%" y="-15%" width="150%" height="140%">
      <feDropShadow dx="0" dy="26" stdDeviation="26" flood-color="#000" flood-opacity="0.34"/>
    </filter>`;
}

/**
 * Very low-amplitude turbulence keeps large flat fills from banding.
 *
 * The noise is composited back into the source's alpha, so it only ever appears
 * where the shape is — without that, turbulence fills the whole filter region
 * and paints a visible rectangle behind the garment.
 */
export function fabricTexture(id, { scale = 0.9, opacity = 0.16 } = {}) {
  return `<filter id="${id}" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="${scale}" numOctaves="3" seed="7" result="noise"/>
      <feColorMatrix in="noise" type="saturate" values="0" result="grey"/>
      <feComponentTransfer in="grey" result="faint">
        <feFuncA type="linear" slope="${opacity}"/>
      </feComponentTransfer>
      <feComposite in="faint" in2="SourceGraphic" operator="in"/>
    </filter>`;
}

/** Evenly spaced horizontal quilting channels, clipped to the garment. */
export function quilting({ from, to, step, xFrom, xTo, stroke, width = 3, opacity = 0.5 }) {
  const rows = [];
  for (let y = from; y <= to; y += step) {
    const sag = 6;
    rows.push(
      `<path d="M ${xFrom} ${n(y)} Q ${n((xFrom + xTo) / 2)} ${n(y + sag)} ${xTo} ${n(y)}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" opacity="${opacity}"/>`,
    );
  }
  return rows.join('');
}

/** Dashed topstitching along an arbitrary path. */
export function stitch(d, color, { width = 2.4, dash = '9 8', opacity = 0.55 } = {}) {
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-dasharray="${dash}" stroke-linecap="round" opacity="${opacity}"/>`;
}

export function svgDocument({ defs, body, background = 'none' }) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">
  <defs>${defs}</defs>
  ${background === 'none' ? '' : `<rect width="${W}" height="${H}" fill="${background}"/>`}
  ${body}
</svg>
`;
}
