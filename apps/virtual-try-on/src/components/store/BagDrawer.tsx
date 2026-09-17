'use client';

import { Icon } from '@/components/ui/Icon';
import { productById } from '@/data/catalog';
import { formatPrice } from '@/lib/format';
import { useStore } from '@/state/store-context';

export function BagDrawer() {
  const { bag, bagOpen, bagTotal, setBagOpen, removeFromBag } = useStore();

  if (!bagOpen) return null;

  return (
    <div className="fixed inset-0 z-[70]">
      <button
        type="button"
        aria-label="Close bag"
        onClick={() => setBagOpen(false)}
        className="absolute inset-0 animate-fade cursor-default bg-ink-950/75 backdrop-blur-sm"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Shopping bag"
        className="absolute inset-y-0 right-0 flex w-full max-w-md animate-sheet flex-col border-l border-ink-700 bg-ink-850"
      >
        <header className="flex items-center justify-between border-b border-ink-700/70 px-5 py-4">
          <h2 className="font-display text-[15px] font-medium text-bone-50">Shopping bag</h2>
          <button
            type="button"
            onClick={() => setBagOpen(false)}
            aria-label="Close bag"
            className="grid size-8 place-items-center rounded-full text-bone-400 transition hover:text-bone-50"
          >
            <Icon name="close" size={16} />
          </button>
        </header>

        {bag.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
            <Icon name="bag" size={26} className="text-bone-600" />
            <p className="text-[13px] text-bone-500">Your bag is empty.</p>
          </div>
        ) : (
          <ul className="scrollarea flex-1 divide-y divide-ink-700/60 overflow-y-auto px-5">
            {bag.map((line) => {
              const product = productById(line.productId);
              if (!product) return null;
              const color = product.colors.find((entry) => entry.id === line.colorId);
              return (
                <li key={`${line.productId}-${line.colorId}-${line.size}`} className="flex gap-4 py-4">
                  <span className="grid size-20 shrink-0 place-items-center rounded-lg border border-ink-700 bg-ink-800">
                    {/* eslint-disable-next-line @next/next/no-img-element -- catalogue artwork is SVG */}
                    <img src={product.image} alt="" className="size-16 object-contain" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-bone-100">{product.name}</p>
                    <p className="mt-1 text-[12px] text-bone-500">
                      {color?.label ?? line.colorId} · {line.size} · Qty {line.quantity}
                    </p>
                    <p className="mt-1.5 text-[13px] text-bone-50">
                      {formatPrice(product.price * line.quantity)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeFromBag(line)}
                    aria-label={`Remove ${product.name}`}
                    className="self-start p-1 text-bone-600 transition hover:text-critical"
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <footer className="border-t border-ink-700/70 p-5">
          <div className="flex items-baseline justify-between">
            <span className="text-[12px] uppercase tracking-[0.12em] text-bone-500">Subtotal</span>
            <span className="font-display text-lg text-bone-50">{formatPrice(bagTotal)}</span>
          </div>
          <p className="mt-1.5 text-[11px] text-bone-600">
            Shipping and duties calculated at checkout.
          </p>
          <button
            type="button"
            disabled={bag.length === 0}
            className="mt-4 w-full rounded-lg bg-bone-50 py-3 text-[13px] font-medium text-ink-900 transition hover:bg-white disabled:opacity-40"
          >
            Checkout
          </button>
        </footer>
      </aside>
    </div>
  );
}
