/**
 * The icon set, drawn inline.
 *
 * One consistent stroke weight and cap style across the whole product, and no
 * icon-font or SVG-sprite dependency to ship.
 */

export type IconName =
  | 'hanger'
  | 'heart'
  | 'heart-filled'
  | 'bag'
  | 'bag-plus'
  | 'search'
  | 'user'
  | 'chevron-down'
  | 'chevron-left'
  | 'chevron-right'
  | 'close'
  | 'star'
  | 'reset'
  | 'key'
  | 'upload'
  | 'camera'
  | 'download'
  | 'share'
  | 'sparkle'
  | 'sun'
  | 'expand'
  | 'trash'
  | 'check'
  | 'alert'
  | 'info'
  | 'compare'
  | 'menu'
  | 'filter';

const PATHS: Record<IconName, string> = {
  hanger: 'M12 4.5a2 2 0 1 0-2 2c1 0 2 .6 2 1.8V9m0 0L3.4 14.6a1.4 1.4 0 0 0 .8 2.6h15.6a1.4 1.4 0 0 0 .8-2.6L12 9Z',
  heart: 'M12 20s-7.5-4.7-7.5-9.4A4.1 4.1 0 0 1 12 7.8a4.1 4.1 0 0 1 7.5 2.8C19.5 15.3 12 20 12 20Z',
  'heart-filled': 'M12 20s-7.5-4.7-7.5-9.4A4.1 4.1 0 0 1 12 7.8a4.1 4.1 0 0 1 7.5 2.8C19.5 15.3 12 20 12 20Z',
  bag: 'M6 8h12l1 12H5L6 8Zm3 0V6a3 3 0 0 1 6 0v2',
  'bag-plus': 'M6 8h12l1 12H5L6 8Zm3 0V6a3 3 0 0 1 6 0v2m-3 5v4m-2-2h4',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 4 4',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0',
  'chevron-down': 'm6 9 6 6 6-6',
  'chevron-left': 'm15 6-6 6 6 6',
  'chevron-right': 'm9 6 6 6-6 6',
  close: 'm6 6 12 12M18 6 6 18',
  star: 'm12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4L4.2 9.7l5.4-.8L12 4Z',
  reset: 'M4 10a8 8 0 1 1 1.5 6M4 5v5h5',
  key: 'M14.5 4a5.5 5.5 0 1 0-4.3 8.9L11 14l-1 1 1 1-1 1 1 1-2 2H6v-3l4.2-4.2A5.5 5.5 0 0 0 14.5 4Zm1.2 3.8h.01',
  upload: 'M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16',
  camera: 'M4 8h3l1.6-2h6.8L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Zm8 3.5a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4Z',
  download: 'M12 4v12m0 0 4.5-4.5M12 16l-4.5-4.5M4 18v.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V18',
  share: 'M12 15V4m0 0L8.5 7.5M12 4l3.5 3.5M5 13v5.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V13',
  sparkle: 'M12 3.5 13.7 9l5.5 1.7-5.5 1.8L12 18l-1.7-5.5L4.8 10.7 10.3 9 12 3.5ZM19 16.5l.7 2 2 .7-2 .8-.7 2-.8-2-2-.8 2-.7.8-2Z',
  sun: 'M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9ZM12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.5 1.5m11.2 11.2 1.5 1.5M19.1 4.9l-1.5 1.5M6.4 17.6l-1.5 1.5',
  expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5m11-5v5h-5',
  trash: 'M5 7h14M10 7V5h4v2m-7 0 .8 13h8.4L17 7',
  check: 'm5 12.5 4.5 4.5L19 7',
  alert: 'M12 8v5m0 3h.01M12 3.5 21 19H3l9-15.5Z',
  info: 'M12 11v6m0-9.5h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
  compare: 'M12 4v16M7 8 3 12l4 4m10-8 4 4-4 4',
  menu: 'M4 7h16M4 12h16M4 17h16',
  filter: 'M4 6h16M7 12h10M10 18h4',
};

const FILLED: IconName[] = ['heart-filled', 'star'];

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
}

export function Icon({ name, size = 18, className, strokeWidth = 1.5 }: IconProps) {
  const filled = FILLED.includes(name);
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? 0 : strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
