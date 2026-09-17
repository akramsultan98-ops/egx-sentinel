import {
  CX,
  fabricGradient,
  fabricTexture,
  halfTorso,
  halfTrouser,
  mirrored,
  mirroredPath,
  quilting,
  sleeve,
  softShadow,
  stitch,
  svgDocument,
} from './draw.mjs';

const n = (v) => Math.round(v * 100) / 100;

function shell({ palette, defs = '', body }) {
  return svgDocument({
    defs: `
      ${fabricGradient('fab', palette)}
      ${fabricGradient('fabDark', { light: palette.base, base: palette.dark, dark: palette.deep ?? palette.dark })}
      ${softShadow('sh')}
      ${fabricTexture('grain')}
      ${defs}`,
    body: `<g filter="url(#sh)">${body}</g>`,
  });
}

/**
 * Generic upper-body garment. Every outerwear/top piece is a variation of this:
 * the silhouette parameters change, then `details` paints the identity on top.
 */
function topGarment({
  palette,
  torso,
  arms,
  open = true,
  collar = 'lapel',
  details = '',
  defs = '',
}) {
  const t = { ...torso };
  const s = { ...arms };
  const torsoPath = halfTorso(t);
  const sleevePath = sleeve(s);
  const hem = t.hemY + (t.hemDip ?? 18);

  const sleeves = mirrored(
    `<path d="${sleevePath}" fill="url(#fab)"/>
     <path d="${sleevePath}" fill="none" stroke="${palette.dark}" stroke-width="2" opacity="0.5"/>`,
  );

  const body = mirrored(`<path d="${torsoPath}" fill="url(#fab)"/>`);

  // An open garment reads as a narrow shadowed opening down the centre front,
  // tapering towards the hem, rather than two offset panels — offsetting the
  // panels exposed the layer beneath them at the silhouette edge.
  const opening = open
    ? `<path d="M ${CX - 13} ${n(t.neckDip + 6)} C ${CX - 15} ${n(t.neckDip + 200)} ${CX - 12} ${n(hem - 200)} ${CX - 9} ${n(hem)}
         L ${CX + 9} ${n(hem)} C ${CX + 12} ${n(hem - 200)} ${CX + 15} ${n(t.neckDip + 200)} ${CX + 13} ${n(t.neckDip + 6)} Z"
       fill="${palette.deep ?? palette.dark}"/>`
    : '';

  const collarShape = renderCollar(collar, t, palette);

  // Every trim detail is clipped to the garment, so topstitching, pockets and
  // ribbing can be drawn generously without escaping the silhouette.
  const silhouette = `${mirroredPath(torsoPath)}${mirroredPath(sleevePath)}`;

  return shell({
    palette,
    defs: `<clipPath id="shape">${silhouette}</clipPath>${defs}`,
    body: `
      ${sleeves}
      ${body}
      ${opening}
      <g clip-path="url(#shape)">${details}</g>
      ${collarShape}
      <g style="mix-blend-mode:overlay" opacity="0.55" filter="url(#grain)">
        ${mirrored(`<path d="${torsoPath}" fill="#808080"/><path d="${sleevePath}" fill="#808080"/>`)}
      </g>`,
  });
}

function renderCollar(kind, t, palette) {
  const y = t.neckDip;
  const nx = CX + t.neckX;
  if (kind === 'none') return '';
  if (kind === 'crew') {
    return `<path d="M ${CX} ${n(y + 16)} C ${n(CX + t.neckX * 0.7)} ${n(y + 14)} ${n(nx + 4)} ${n(t.shoulderY + 6)} ${n(nx + 10)} ${n(t.shoulderY - 2)}
      C ${n(nx - 6)} ${n(t.shoulderY + 30)} ${n(CX + 30)} ${n(y + 42)} ${CX} ${n(y + 42)}
      C ${n(CX - 30)} ${n(y + 42)} ${n(CX - nx + CX - 6)} ${n(t.shoulderY + 30)} ${n(CX - t.neckX - 10)} ${n(t.shoulderY - 2)}
      C ${n(CX - t.neckX - 4)} ${n(t.shoulderY + 6)} ${n(CX - t.neckX * 0.7)} ${n(y + 14)} ${CX} ${n(y + 16)} Z"
      fill="${palette.dark}"/>`;
  }
  if (kind === 'stand') {
    return mirrored(
      `<path d="M ${CX} ${n(y - 26)} L ${n(nx + 6)} ${n(t.shoulderY - 14)} C ${n(nx + 14)} ${n(t.shoulderY + 16)} ${n(nx - 2)} ${n(t.shoulderY + 24)} ${n(nx - 8)} ${n(t.shoulderY + 18)}
        C ${n(nx - 20)} ${n(y + 10)} ${n(CX + 20)} ${n(y + 12)} ${CX} ${n(y + 10)} Z" fill="url(#fab)" stroke="${palette.dark}" stroke-width="2"/>`,
    );
  }
  if (kind === 'hood') {
    return `<path d="M ${CX} ${n(y - 96)} C ${n(CX + 86)} ${n(y - 92)} ${n(nx + 66)} ${n(y - 20)} ${n(nx + 40)} ${n(t.shoulderY + 34)}
      C ${n(CX + 40)} ${n(y + 56)} ${n(CX - 40)} ${n(y + 56)} ${n(CX - t.neckX - 40)} ${n(t.shoulderY + 34)}
      C ${n(CX - t.neckX - 66)} ${n(y - 20)} ${n(CX - 86)} ${n(y - 92)} ${CX} ${n(y - 96)} Z" fill="url(#fab)" stroke="${palette.dark}" stroke-width="2"/>
      <path d="M ${CX} ${n(y - 62)} C ${n(CX + 52)} ${n(y - 58)} ${n(CX + 62)} ${n(y + 6)} ${n(CX + 44)} ${n(y + 40)}
      C ${CX} ${n(y + 62)} ${n(CX - 44)} ${n(y + 40)} ${n(CX - 44)} ${n(y + 40)}
      C ${n(CX - 62)} ${n(y + 6)} ${n(CX - 52)} ${n(y - 58)} ${CX} ${n(y - 62)} Z" fill="${palette.deep ?? palette.dark}" opacity="0.9"/>`;
  }
  // lapel
  return mirrored(
    `<path d="M ${n(nx)} ${n(t.shoulderY + 2)} C ${n(nx + 14)} ${n(t.shoulderY + 70)} ${n(CX + 74)} ${n(y + 150)} ${n(CX + 30)} ${n(y + 250)}
      C ${n(CX + 16)} ${n(y + 180)} ${n(CX + 6)} ${n(y + 90)} ${CX} ${n(y + 16)} Z"
      fill="url(#fab)" stroke="${palette.dark}" stroke-width="2.5" stroke-linejoin="round"/>`,
  );
}

const BASE_TORSO = {
  neckX: 44,
  neckDip: 250,
  shoulderY: 236,
  shoulderX: 152,
  shoulderDrop: 26,
  armpitX: 128,
  armpitY: 372,
  waistX: 132,
  waistY: 590,
  hemX: 140,
  hemY: 760,
  hemDip: 18,
};

const BASE_ARMS = {
  shoulderY: 236,
  shoulderX: 152,
  shoulderDrop: 26,
  armpitX: 128,
  armpitY: 372,
  cuffY: 660,
  cuffOuter: 208,
  cuffInner: 150,
  bow: 26,
};

function buttons(xs, ys, color, r = 9) {
  return ys
    .map((y) => xs.map((x) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${color}" opacity="0.92"/>`).join(''))
    .join('');
}

/* ------------------------------------------------------------------ */
/* Catalogue pieces                                                     */
/* ------------------------------------------------------------------ */

export const GARMENTS = {
  'trench-coat': (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, hemY: 872, waistX: 138, hemX: 168, hemDip: 22 },
      arms: { ...BASE_ARMS, cuffY: 704, cuffOuter: 214 },
      collar: 'lapel',
      details: `
        ${buttons([CX - 58, CX + 58], [520, 596, 672], palette.hardware)}
        <path d="M ${CX - 176} 600 h 92 a 10 10 0 0 1 10 10 v 74 a 10 10 0 0 1 -10 10 h -92 a 10 10 0 0 1 -10 -10 v -74 a 10 10 0 0 1 10 -10 z" fill="${palette.dark}" opacity="0.45"/>
        <path d="M ${CX + 84} 600 h 92 a 10 10 0 0 1 10 10 v 74 a 10 10 0 0 1 -10 10 h -92 a 10 10 0 0 1 -10 -10 v -74 a 10 10 0 0 1 10 -10 z" fill="${palette.dark}" opacity="0.45"/>
        <rect x="${CX - 178}" y="560" width="356" height="26" rx="13" fill="${palette.dark}" opacity="0.7"/>
        <rect x="${CX - 40}" y="556" width="80" height="34" rx="12" fill="${palette.hardware}" opacity="0.85"/>
        ${stitch(`M ${CX - 150} 300 C ${CX - 130} 420 ${CX - 120} 560 ${CX - 126} 760`, palette.stitch)}
        ${stitch(`M ${CX + 150} 300 C ${CX + 130} 420 ${CX + 120} 560 ${CX + 126} 760`, palette.stitch)}`,
    }),

  puffer: (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, shoulderX: 168, armpitX: 150, waistX: 152, hemX: 150, hemY: 726, hemDip: 14 },
      arms: { ...BASE_ARMS, shoulderX: 168, armpitX: 150, cuffY: 664, cuffOuter: 228, cuffInner: 168, bow: 34 },
      collar: 'stand',
      details: `
        ${quilting({ from: 268, to: 730, step: 46, xFrom: CX - 250, xTo: CX + 250, stroke: palette.dark, width: 4, opacity: 0.5 })}
        <rect x="${CX - 5}" y="250" width="10" height="470" rx="5" fill="${palette.hardware}" opacity="0.8"/>
        <rect x="${CX - 11}" y="690" width="22" height="34" rx="8" fill="${palette.hardware}"/>`,
    }),

  'denim-jacket': (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, hemY: 672, waistX: 128, hemX: 134, hemDip: 10 },
      arms: { ...BASE_ARMS, cuffY: 628, cuffOuter: 196, cuffInner: 146 },
      collar: 'lapel',
      details: `
        <rect x="${CX - 178}" y="646" width="356" height="34" rx="8" fill="${palette.dark}" opacity="0.55"/>
        ${buttons([CX + 26], [410, 484, 558, 630], palette.hardware, 8)}
        <path d="M ${CX - 154} 392 h 88 l 8 76 h -96 z" fill="${palette.dark}" opacity="0.4"/>
        <path d="M ${CX + 66} 392 h 88 l 0 76 h -96 z" fill="${palette.dark}" opacity="0.4"/>
        ${stitch(`M ${CX - 158} 388 h 100`, palette.stitch, { opacity: 0.8 })}
        ${stitch(`M ${CX + 62} 388 h 100`, palette.stitch, { opacity: 0.8 })}
        ${stitch(`M ${CX - 180} 378 h 360`, palette.stitch, { opacity: 0.7 })}
        ${stitch(`M ${CX + 20} 300 v 350`, palette.stitch, { opacity: 0.8 })}
        ${stitch(`M ${CX - 174} 652 h 352`, palette.stitch, { opacity: 0.8 })}`,
    }),

  bomber: (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, shoulderX: 162, armpitX: 144, waistX: 146, hemX: 128, hemY: 686, hemDip: 8 },
      arms: { ...BASE_ARMS, shoulderX: 162, armpitX: 144, cuffY: 636, cuffOuter: 214, cuffInner: 162, bow: 32 },
      collar: 'crew',
      details: `
        <rect x="${CX - 130}" y="660" width="260" height="46" rx="16" fill="${palette.dark}" opacity="0.85"/>
        ${quilting({ from: 668, to: 700, step: 10, xFrom: CX - 126, xTo: CX + 126, stroke: palette.deep ?? palette.dark, width: 2, opacity: 0.45 })}
        <rect x="${CX - 5}" y="282" width="10" height="386" rx="5" fill="${palette.hardware}" opacity="0.85"/>
        <path d="M ${CX + 52} 470 h 104 a 8 8 0 0 1 8 8 v 18 a 8 8 0 0 1 -8 8 h -104 z" fill="${palette.dark}" opacity="0.5"/>
        <path d="M ${CX - 164} 470 h 104 v 34 h -104 a 8 8 0 0 1 -8 -8 v -18 a 8 8 0 0 1 8 -8 z" fill="${palette.dark}" opacity="0.5"/>`,
    }),

  biker: (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, hemY: 660, waistX: 126, hemX: 132, hemDip: 8 },
      arms: { ...BASE_ARMS, cuffY: 640, cuffOuter: 198, cuffInner: 148 },
      collar: 'lapel',
      details: `
        <rect x="${CX - 176}" y="636" width="352" height="30" rx="8" fill="${palette.dark}" opacity="0.6"/>
        <rect x="${CX + 34}" y="300" width="9" height="330" rx="4.5" fill="${palette.hardware}" opacity="0.9"/>
        <rect x="${CX + 26}" y="612" width="26" height="40" rx="9" fill="${palette.hardware}"/>
        <path d="M ${CX - 150} 430 l 96 26 v 30 l -96 -26 z" fill="${palette.hardware}" opacity="0.65"/>
        <path d="M ${CX + 66} 430 l 96 26 v 30 l -96 -26 z" fill="${palette.hardware}" opacity="0.5"/>
        ${stitch(`M ${CX - 186} 520 C ${CX - 90} 548 ${CX + 90} 548 ${CX + 186} 520`, palette.stitch, { dash: '6 10', opacity: 0.45 })}`,
    }),

  tee: (palette) =>
    topGarment({
      palette,
      open: false,
      torso: { ...BASE_TORSO, neckDip: 262, hemY: 700, waistX: 142, hemX: 148, hemDip: 14 },
      arms: { ...BASE_ARMS, cuffY: 452, cuffOuter: 202, cuffInner: 140, bow: 12 },
      collar: 'crew',
      details: `${stitch(`M ${CX - 148} 690 h 296`, palette.stitch, { dash: '7 9', opacity: 0.4 })}`,
    }),

  knit: (palette) =>
    topGarment({
      palette,
      open: false,
      torso: { ...BASE_TORSO, neckDip: 258, hemY: 720, waistX: 146, hemX: 150, hemDip: 12 },
      arms: { ...BASE_ARMS, cuffY: 672, cuffOuter: 210, cuffInner: 152, bow: 22 },
      collar: 'crew',
      details: `
        ${quilting({ from: 272, to: 732, step: 22, xFrom: CX - 240, xTo: CX + 240, stroke: palette.dark, width: 1.6, opacity: 0.28 })}
        <rect x="${CX - 152}" y="694" width="304" height="40" rx="14" fill="${palette.dark}" opacity="0.6"/>`,
    }),

  hoodie: (palette) =>
    topGarment({
      palette,
      open: false,
      torso: { ...BASE_TORSO, neckDip: 266, shoulderX: 166, armpitX: 148, waistX: 156, hemX: 152, hemY: 736, hemDip: 12 },
      arms: { ...BASE_ARMS, shoulderX: 166, armpitX: 148, cuffY: 688, cuffOuter: 222, cuffInner: 164, bow: 30 },
      collar: 'hood',
      details: `
        <path d="M ${CX - 116} 566 h 232 a 12 12 0 0 1 12 12 v 92 h -256 v -92 a 12 12 0 0 1 12 -12 z" fill="${palette.dark}" opacity="0.45"/>
        <rect x="${CX - 150}" y="706" width="300" height="42" rx="14" fill="${palette.dark}" opacity="0.6"/>
        <path d="M ${CX - 26} 298 v 96" stroke="${palette.stitch}" stroke-width="7" stroke-linecap="round" fill="none"/>
        <path d="M ${CX + 26} 298 v 96" stroke="${palette.stitch}" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    }),

  shirt: (palette) =>
    topGarment({
      palette,
      torso: { ...BASE_TORSO, hemY: 716, waistX: 128, hemX: 136, hemDip: 20 },
      arms: { ...BASE_ARMS, cuffY: 686, cuffOuter: 200, cuffInner: 148 },
      collar: 'lapel',
      details: `
        ${buttons([CX + 4], [330, 398, 466, 534, 602, 670], palette.hardware, 7)}
        <path d="M ${CX - 154} 384 h 92 l 6 70 h -98 z" fill="${palette.dark}" opacity="0.32"/>
        ${stitch(`M ${CX + 34} 290 v 420`, palette.stitch, { dash: '6 8', opacity: 0.4 })}`,
    }),

  trousers: (palette) => {
    const cfg = {
      waistY: 250,
      waistX: 128,
      hipX: 146,
      hipY: 390,
      kneeX: 96,
      kneeY: 620,
      hemX: 86,
      hemY: 880,
      inseamX: 16,
      crotchY: 470,
    };
    return shell({
      palette,
      body: `
        ${mirrored(`<path d="${halfTrouser(cfg)}" fill="url(#fab)" stroke="${palette.dark}" stroke-width="2"/>`)}
        <rect x="${CX - 130}" y="238" width="260" height="46" rx="10" fill="url(#fabDark)"/>
        <path d="M ${CX} 284 v 596" stroke="${palette.dark}" stroke-width="3" opacity="0.5" fill="none"/>
        ${stitch(`M ${CX - 62} 300 C ${CX - 74} 380 ${CX - 70} 520 ${CX - 58} 860`, palette.stitch, { opacity: 0.4 })}
        ${stitch(`M ${CX + 62} 300 C ${CX + 74} 380 ${CX + 70} 520 ${CX + 58} 860`, palette.stitch, { opacity: 0.4 })}
        <circle cx="${CX}" cy="261" r="8" fill="${palette.hardware}"/>
        <g style="mix-blend-mode:overlay" opacity="0.45" filter="url(#grain)">${mirrored(`<path d="${halfTrouser(cfg)}" fill="#808080"/>`)}</g>`,
    });
  },

  sneaker: (palette) =>
    shell({
      palette,
      body: `
        <path d="M 150 700 C 150 600 220 560 300 556 C 372 552 420 512 470 486 C 528 456 578 470 596 520 C 612 566 646 588 672 616 C 700 646 700 700 662 714 C 600 736 250 738 186 730 C 160 726 150 716 150 700 Z"
          fill="url(#fab)" stroke="${palette.dark}" stroke-width="3"/>
        <path d="M 148 700 C 148 676 158 664 186 662 C 300 650 596 652 668 662 C 700 666 706 690 700 710 C 692 736 656 748 600 750 C 420 756 240 754 196 746 C 162 740 148 724 148 700 Z"
          fill="${palette.sole ?? '#f4f1ea'}" stroke="${palette.dark}" stroke-width="3"/>
        <path d="M 300 560 C 350 594 392 626 420 668" stroke="${palette.dark}" stroke-width="3" fill="none" opacity="0.5"/>
        <path d="M 366 544 C 412 580 452 614 480 660" stroke="${palette.dark}" stroke-width="3" fill="none" opacity="0.4"/>
        <path d="M 470 490 C 512 500 540 530 548 572 C 556 614 542 646 520 664" fill="${palette.dark}" opacity="0.3"/>
        ${quilting({ from: 578, to: 640, step: 26, xFrom: 240, xTo: 340, stroke: palette.stitch, width: 4, opacity: 0.7 })}
        <circle cx="596" cy="560" r="16" fill="${palette.hardware}" opacity="0.7"/>
        <g style="mix-blend-mode:overlay" opacity="0.4" filter="url(#grain)"><path d="M 150 700 C 150 600 220 560 300 556 C 372 552 420 512 470 486 C 528 456 578 470 596 520 C 612 566 646 588 672 616 C 700 646 700 700 662 714 C 600 736 250 738 186 730 C 160 726 150 716 150 700 Z" fill="#808080"/></g>`,
    }),

  cap: (palette) =>
    shell({
      palette,
      body: `
        <path d="M 250 560 C 244 452 310 380 400 380 C 490 380 556 452 550 560 C 552 580 540 590 520 590 L 280 590 C 260 590 248 580 250 560 Z"
          fill="url(#fab)" stroke="${palette.dark}" stroke-width="3"/>
        <path d="M 400 380 C 420 440 430 510 428 590" stroke="${palette.dark}" stroke-width="2.5" fill="none" opacity="0.45"/>
        <path d="M 400 380 C 380 440 370 510 372 590" stroke="${palette.dark}" stroke-width="2.5" fill="none" opacity="0.45"/>
        <path d="M 264 566 C 330 600 470 600 536 566 C 596 566 640 588 644 606 C 648 628 604 640 540 642 L 300 642 C 250 640 226 622 232 600 C 236 582 246 568 264 566 Z"
          fill="url(#fabDark)" stroke="${palette.dark}" stroke-width="3"/>
        <circle cx="400" cy="384" r="14" fill="${palette.dark}"/>
        <g style="mix-blend-mode:overlay" opacity="0.45" filter="url(#grain)"><path d="M 250 560 C 244 452 310 380 400 380 C 490 380 556 452 550 560 C 552 580 540 590 520 590 L 280 590 C 260 590 248 580 250 560 Z" fill="#808080"/></g>`,
    }),
};
