'use client';

import { useState } from 'react';

import { Icon } from '@/components/ui/Icon';
import { Modal } from '@/components/ui/Modal';
import { categoryLabel, type Product } from '@/data/catalog';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/format';

interface QuickViewProps {
  product: Product | null;
  onClose(): void;
  onAddToBag(product: Product, options: { colorId: string; size: string }): void;
  onTryOn(product: Product, options: { colorId: string; size: string }): void;
  inFittingRoom: boolean;
}

/** Colour and size are chosen here, then carried into both the bag and the fitting room. */
export function QuickView({ product, ...rest }: QuickViewProps) {
  if (!product) return null;
  // Keyed on the product so selections initialise from it rather than being
  // reset by an effect after the dialog has already painted.
  return <QuickViewBody key={product.id} product={product} {...rest} />;
}

function QuickViewBody({
  product,
  onClose,
  onAddToBag,
  onTryOn,
  inFittingRoom,
}: Omit<QuickViewProps, 'product'> & { product: Product }) {
  const [colorId, setColorId] = useState(() => product.colors[0]?.id ?? '');
  const [size, setSize] = useState(
    () => product.sizes[Math.floor(product.sizes.length / 2)] ?? '',
  );

  const options = { colorId, size };

  return (
    <Modal open onClose={onClose} labelledBy="quick-view-title" size="wide">
      <div className="grid gap-0 md:grid-cols-[1.05fr_1fr]">
        <div className="relative flex items-center justify-center border-b border-ink-700/60 bg-ink-800/60 p-8 md:border-b-0 md:border-r">
          {/* eslint-disable-next-line @next/next/no-img-element -- catalogue artwork is SVG */}
          <img
            src={product.image}
            alt={product.name}
            className="max-h-[42vh] w-auto object-contain md:max-h-[58vh]"
          />
        </div>

        <div className="scrollarea max-h-[60vh] overflow-y-auto p-6 sm:p-7">
          <p className="text-eyebrow">{categoryLabel(product.category)}</p>
          <h2 id="quick-view-title" className="mt-2 font-display text-2xl font-medium text-bone-50">
            {product.name}
          </h2>

          <div className="mt-3 flex items-center gap-3">
            <span className="text-lg text-bone-50">{formatPrice(product.price)}</span>
            {product.compareAtPrice ? (
              <span className="text-[13px] text-bone-600 line-through">
                {formatPrice(product.compareAtPrice)}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 text-[12px] text-bone-500">
              <Icon name="star" size={12} className="text-accent-500" />
              {product.rating.toFixed(1)} · {product.reviews} reviews
            </span>
          </div>

          <p className="mt-5 text-[13px] leading-relaxed text-bone-300">{product.description}</p>

          <fieldset className="mt-7">
            <legend className="text-eyebrow">Colour</legend>
            <div className="mt-3 flex flex-wrap gap-2.5">
              {product.colors.map((color) => (
                <button
                  key={color.id}
                  type="button"
                  onClick={() => setColorId(color.id)}
                  aria-pressed={colorId === color.id}
                  title={color.label}
                  className={cn(
                    'flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3 text-[12px] transition',
                    colorId === color.id
                      ? 'border-accent-500 text-bone-50'
                      : 'border-ink-600 text-bone-400 hover:border-ink-500',
                  )}
                >
                  <span
                    className="size-5 rounded-full border border-ink-500"
                    style={{ background: color.hex }}
                  />
                  {color.label}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="mt-6">
            <legend className="text-eyebrow">Size</legend>
            <div className="mt-3 flex flex-wrap gap-2">
              {product.sizes.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setSize(option)}
                  aria-pressed={size === option}
                  className={cn(
                    'min-w-11 rounded-md border px-3 py-2 text-[12px] transition',
                    size === option
                      ? 'border-accent-500 bg-accent-500/10 text-bone-50'
                      : 'border-ink-600 text-bone-400 hover:border-ink-500 hover:text-bone-100',
                  )}
                >
                  {option}
                </button>
              ))}
            </div>
          </fieldset>

          <dl className="mt-7 space-y-2 border-t border-ink-700/70 pt-5 text-[12px]">
            <div className="flex justify-between gap-4">
              <dt className="text-bone-600">Fabric</dt>
              <dd className="text-right text-bone-300">{product.fabric}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-bone-600">Care</dt>
              <dd className="text-right text-bone-300">{product.care}</dd>
            </div>
          </dl>

          <div className="mt-7 flex flex-col gap-2.5 sm:flex-row">
            <button
              type="button"
              onClick={() => onTryOn(product, options)}
              className={cn(
                'inline-flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-3 text-[13px] font-medium transition',
                inFittingRoom
                  ? 'bg-accent-500 text-ink-900 hover:bg-accent-400'
                  : 'border border-accent-500/50 text-accent-300 hover:bg-accent-500/10',
              )}
            >
              <Icon name="hanger" size={16} />
              {inFittingRoom ? 'In the fitting room' : 'Try on'}
            </button>
            <button
              type="button"
              onClick={() => onAddToBag(product, options)}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-bone-50 px-4 py-3 text-[13px] font-medium text-ink-900 transition hover:bg-white"
            >
              <Icon name="bag-plus" size={16} />
              Add to bag
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
