'use client';

import { memo } from 'react';

import { Icon } from '@/components/ui/Icon';
import type { Product } from '@/data/catalog';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/format';

interface ProductCardProps {
  product: Product;
  wishlisted: boolean;
  inFittingRoom: boolean;
  onToggleWishlist(): void;
  onToggleFittingRoom(): void;
  onAddToBag(): void;
  onQuickView(): void;
}

/**
 * The card carries four actions without ever showing four buttons at rest:
 * wishlist and rating sit in the corners, the hanger fades in on hover next to
 * the wishlist, and add-to-bag lives in the cut corner of the image. Everything
 * stays reachable by keyboard and permanently visible on touch.
 */
export const ProductCard = memo(function ProductCard({
  product,
  wishlisted,
  inFittingRoom,
  onToggleWishlist,
  onToggleFittingRoom,
  onAddToBag,
  onQuickView,
}: ProductCardProps) {
  const discount = product.compareAtPrice
    ? Math.round((1 - product.price / product.compareAtPrice) * 100)
    : 0;

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-card border border-ink-700/70 bg-ink-850 transition-colors duration-300 hover:border-ink-600">
      <div className="relative">
        <button
          type="button"
          onClick={onQuickView}
          className="block w-full cursor-zoom-in"
          aria-label={`Quick view: ${product.name}`}
        >
          <span className="relative block aspect-[4/5] overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element -- catalogue artwork is SVG; the optimiser cannot process it */}
            <img
              src={product.image}
              alt={product.name}
              loading="lazy"
              decoding="async"
              className="size-full object-contain p-6 transition-transform duration-[600ms] ease-[var(--ease-out-soft)] group-hover:scale-[1.045] sm:p-8"
            />
          </span>
        </button>

        <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between">
          <div className="pointer-events-auto flex flex-col gap-2">
            <CornerButton
              label={wishlisted ? `Remove ${product.name} from wishlist` : `Save ${product.name}`}
              onClick={onToggleWishlist}
              active={wishlisted}
              alwaysVisible
            >
              <Icon name={wishlisted ? 'heart-filled' : 'heart'} size={15} />
            </CornerButton>

            <CornerButton
              label={
                inFittingRoom
                  ? `Remove ${product.name} from the fitting room`
                  : `Try on ${product.name}`
              }
              onClick={onToggleFittingRoom}
              active={inFittingRoom}
              accent
            >
              <Icon name="hanger" size={15} />
            </CornerButton>
          </div>

          <div className="flex flex-col items-end gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-ink-900/85 px-2 py-1 text-[11px] font-medium text-bone-100 backdrop-blur">
              <Icon name="star" size={11} className="text-accent-500" />
              {product.rating.toFixed(1)}
            </span>
            {product.badge === 'new' ? <Flag>New</Flag> : null}
            {discount > 0 ? <Flag tone="sale">−{discount}%</Flag> : null}
          </div>
        </div>
      </div>

      <div className="relative mt-auto flex items-end justify-between gap-3 border-t border-ink-700/60 p-4">
        <div className="min-w-0">
          <h3 className="truncate text-[13px] font-medium text-bone-100">{product.name}</h3>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-[15px] font-medium text-bone-50">{formatPrice(product.price)}</span>
            {product.compareAtPrice ? (
              <>
                <span className="text-[12px] text-bone-600 line-through">
                  {formatPrice(product.compareAtPrice)}
                </span>
                <span className="rounded-sm bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-accent-400">
                  Sale
                </span>
              </>
            ) : null}
          </p>
        </div>

        {/* The cut corner: a quiet chevron at rest, a full accent wedge on hover. */}
        <button
          type="button"
          onClick={onAddToBag}
          aria-label={`Add ${product.name} to bag`}
          className="group/bag relative -m-4 ml-0 grid size-[68px] shrink-0 place-items-end justify-items-end overflow-hidden p-4 text-bone-400 transition-colors hover:text-ink-900 focus-visible:text-ink-900"
        >
          <span
            aria-hidden="true"
            className="absolute -bottom-6 -right-6 size-24 rounded-tl-full bg-accent-500 opacity-0 transition-all duration-300 ease-[var(--ease-out-soft)] group-hover/bag:opacity-100 group-focus-visible/bag:opacity-100"
          />
          <Icon name="bag-plus" size={17} className="relative" />
        </button>
      </div>
    </article>
  );
});

function CornerButton({
  children,
  label,
  onClick,
  active,
  accent,
  alwaysVisible,
}: {
  children: React.ReactNode;
  label: string;
  onClick(): void;
  active?: boolean;
  accent?: boolean;
  alwaysVisible?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        'grid size-8 place-items-center rounded-full border backdrop-blur transition-all duration-300',
        // Hidden until hover on pointer devices, always visible on touch.
        alwaysVisible || active
          ? 'opacity-100'
          : 'opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100',
        active && accent
          ? 'border-accent-500 bg-accent-500 text-ink-900'
          : active
            ? 'border-accent-500/60 bg-ink-900/80 text-accent-400'
            : accent
              ? 'border-accent-500/40 bg-accent-500/15 text-accent-400 hover:bg-accent-500 hover:text-ink-900'
              : 'border-ink-600/80 bg-ink-900/70 text-bone-300 hover:text-bone-50',
      )}
    >
      {children}
    </button>
  );
}

function Flag({ children, tone }: { children: React.ReactNode; tone?: 'sale' }) {
  return (
    <span
      className={cn(
        'rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] backdrop-blur',
        tone === 'sale' ? 'bg-accent-500 text-ink-900' : 'bg-ink-900/85 text-bone-300',
      )}
    >
      {children}
    </span>
  );
}
