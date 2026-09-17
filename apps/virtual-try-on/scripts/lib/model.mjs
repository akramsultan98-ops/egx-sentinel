/**
 * The demo fitting-room figure: a neutral studio mannequin, deliberately
 * featureless so it reads as a stand-in rather than a depiction of a person.
 * Shoppers replace it by uploading their own photo.
 */

const W = 800;
const H = 1200;
const CX = W / 2;

function limb(d, fill, stroke) {
  return `<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="2" stroke-linejoin="round"/>`;
}

export function modelFigure({ skin = '#d9d2c7', skinDark = '#bdb4a6', top = '#2f3238', bottom = '#3b3f46', shoe = '#e9e5dd' } = {}) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">
  <defs>
    <linearGradient id="backdrop" x1="0.2" y1="0" x2="0.9" y2="1">
      <stop offset="0" stop-color="#e8e6e1"/>
      <stop offset="0.55" stop-color="#dcd9d3"/>
      <stop offset="1" stop-color="#c8c4bd"/>
    </linearGradient>
    <radialGradient id="floor" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#000" stop-opacity="0.34"/>
      <stop offset="1" stop-color="#000" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="skinG" x1="0.2" y1="0" x2="0.9" y2="1">
      <stop offset="0" stop-color="${skin}"/>
      <stop offset="1" stop-color="${skinDark}"/>
    </linearGradient>
    <linearGradient id="topG" x1="0.15" y1="0" x2="0.9" y2="1">
      <stop offset="0" stop-color="${top}"/>
      <stop offset="1" stop-color="#20232a"/>
    </linearGradient>
    <linearGradient id="botG" x1="0.15" y1="0" x2="0.9" y2="1">
      <stop offset="0" stop-color="${bottom}"/>
      <stop offset="1" stop-color="#282b31"/>
    </linearGradient>
  </defs>

  <rect width="${W}" height="${H}" fill="url(#backdrop)"/>
  <ellipse cx="${CX}" cy="1118" rx="230" ry="46" fill="url(#floor)"/>

  <!-- head + neck -->
  ${limb(`M ${CX} 96 C ${CX + 58} 96 ${CX + 74} 142 ${CX + 72} 186 C ${CX + 70} 240 ${CX + 44} 274 ${CX} 274 C ${CX - 44} 274 ${CX - 70} 240 ${CX - 72} 186 C ${CX - 74} 142 ${CX - 58} 96 ${CX} 96 Z`, 'url(#skinG)', skinDark)}
  ${limb(`M ${CX - 32} 262 h 64 v 62 h -64 z`, 'url(#skinG)', skinDark)}

  <!-- torso base layer -->
  ${limb(`M ${CX} 308 C ${CX + 58} 308 ${CX + 126} 336 ${CX + 138} 386 C ${CX + 150} 444 ${CX + 142} 546 ${CX + 132} 622 L ${CX - 132} 622 C ${CX - 142} 546 ${CX - 150} 444 ${CX - 138} 386 C ${CX - 126} 336 ${CX - 58} 308 ${CX} 308 Z`, 'url(#topG)', '#191c21')}

  <!-- arms -->
  ${limb(`M ${CX + 128} 356 C ${CX + 164} 384 ${CX + 176} 470 ${CX + 178} 552 C ${CX + 180} 622 ${CX + 176} 676 ${CX + 168} 712 L ${CX + 126} 706 C ${CX + 128} 640 ${CX + 126} 520 ${CX + 112} 420 Z`, 'url(#topG)', '#191c21')}
  ${limb(`M ${CX - 128} 356 C ${CX - 164} 384 ${CX - 176} 470 ${CX - 178} 552 C ${CX - 180} 622 ${CX - 176} 676 ${CX - 168} 712 L ${CX - 126} 706 C ${CX - 128} 640 ${CX - 126} 520 ${CX - 112} 420 Z`, 'url(#topG)', '#191c21')}
  ${limb(`M ${CX + 168} 706 C ${CX + 186} 742 ${CX + 184} 784 ${CX + 166} 796 C ${CX + 146} 806 ${CX + 132} 780 ${CX + 128} 742 L ${CX + 126} 704 Z`, 'url(#skinG)', skinDark)}
  ${limb(`M ${CX - 168} 706 C ${CX - 186} 742 ${CX - 184} 784 ${CX - 166} 796 C ${CX - 146} 806 ${CX - 132} 780 ${CX - 128} 742 L ${CX - 126} 704 Z`, 'url(#skinG)', skinDark)}

  <!-- legs -->
  ${limb(`M ${CX - 130} 610 L ${CX - 8} 610 L ${CX - 12} 1058 L ${CX - 104} 1058 C ${CX - 116} 900 ${CX - 128} 740 ${CX - 130} 610 Z`, 'url(#botG)', '#191c21')}
  ${limb(`M ${CX + 130} 610 L ${CX + 8} 610 L ${CX + 12} 1058 L ${CX + 104} 1058 C ${CX + 116} 900 ${CX + 128} 740 ${CX + 130} 610 Z`, 'url(#botG)', '#191c21')}

  <!-- shoes -->
  ${limb(`M ${CX - 110} 1050 h 102 c 6 26 16 40 34 46 c 10 4 10 16 -4 18 h -142 c -10 0 -14 -8 -12 -20 c 8 -12 18 -24 22 -44 z`, shoe, '#b9b4aa')}
  ${limb(`M ${CX + 110} 1050 h -102 c -6 26 -16 40 -34 46 c -10 4 -10 16 4 18 h 142 c 10 0 14 -8 12 -20 c -8 -12 -18 -24 -22 -44 z`, shoe, '#b9b4aa')}
</svg>
`;
}
