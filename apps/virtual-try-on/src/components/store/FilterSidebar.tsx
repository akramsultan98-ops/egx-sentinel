'use client';

import { Icon } from '@/components/ui/Icon';
import { CATEGORIES, PRICE_BOUNDS, type Product } from '@/data/catalog';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/format';
import { useStore } from '@/state/store-context';

/**
 * Catalogue filters. Counts are computed against the other active filters, so a
 * category that would return nothing reads as disabled rather than looking
 * broken when it is selected.
 */
export function FilterSidebar({ products, className }: { products: Product[]; className?: string }) {
  const { filters, setFilters, resetFilters } = useStore();

  const countFor = (categoryId: string) =>
    products.filter((product) => {
      if (categoryId !== 'all' && product.category !== categoryId) return false;
      if (product.price > filters.maxPrice) return false;
      if (filters.onSaleOnly && !product.compareAtPrice) return false;
      return true;
    }).length;

  const dirty =
    filters.category !== 'all' ||
    filters.query !== '' ||
    filters.onSaleOnly ||
    filters.maxPrice !== PRICE_BOUNDS.max;

  return (
    <aside className={cn('rounded-panel border border-ink-700/70 bg-ink-850/60 p-5', className)}>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-[15px] font-medium text-bone-50">Filters</h2>
        <button
          type="button"
          onClick={resetFilters}
          disabled={!dirty}
          className="inline-flex items-center gap-1.5 text-[12px] text-bone-500 transition hover:text-bone-100 disabled:pointer-events-none disabled:opacity-40"
        >
          <Icon name="reset" size={13} />
          Reset Filters
        </button>
      </div>

      <label className="mt-5 flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800 px-3 py-2.5 transition focus-within:border-ink-500">
        <Icon name="search" size={15} className="shrink-0 text-bone-600" />
        <span className="sr-only">Search products</span>
        <input
          value={filters.query}
          onChange={(event) => setFilters({ query: event.target.value })}
          placeholder="Search products"
          className="w-full bg-transparent text-[13px] text-bone-100 outline-none placeholder:text-bone-600"
        />
      </label>

      <section className="mt-7">
        <h3 className="text-eyebrow">Category</h3>
        <ul className="mt-3 space-y-0.5">
          {CATEGORIES.map((category) => {
            const count = countFor(category.id);
            const selected = filters.category === category.id;
            return (
              <li key={category.id}>
                <button
                  type="button"
                  onClick={() => setFilters({ category: category.id })}
                  disabled={count === 0 && !selected}
                  className={cn(
                    'flex w-full items-center justify-between rounded-lg px-3 py-2 text-[13px] transition',
                    selected
                      ? 'bg-accent-500/12 text-accent-300'
                      : 'text-bone-300 hover:bg-ink-800 hover:text-bone-50',
                    count === 0 && !selected && 'pointer-events-none opacity-35',
                  )}
                  aria-pressed={selected}
                >
                  <span>{category.label}</span>
                  <span className={cn('text-[11px]', selected ? 'text-accent-500' : 'text-bone-600')}>
                    {count}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-7">
        <div className="flex items-baseline justify-between">
          <h3 className="text-eyebrow">Price Range</h3>
          <span className="text-[12px] text-bone-300">
            {formatPrice(PRICE_BOUNDS.min)} – {formatPrice(filters.maxPrice)}
          </span>
        </div>
        <input
          type="range"
          min={PRICE_BOUNDS.min}
          max={PRICE_BOUNDS.max}
          step={10}
          value={filters.maxPrice}
          onChange={(event) => setFilters({ maxPrice: Number(event.target.value) })}
          aria-label="Maximum price"
          className="mt-4 h-1 w-full cursor-pointer appearance-none rounded-full bg-ink-600 accent-accent-500 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-500"
        />
      </section>

      <section className="mt-7 border-t border-ink-700/70 pt-5">
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <span className="text-[13px] text-bone-300">On sale only</span>
          <span className="relative inline-flex">
            <input
              type="checkbox"
              checked={filters.onSaleOnly}
              onChange={(event) => setFilters({ onSaleOnly: event.target.checked })}
              className="peer sr-only"
            />
            <span className="h-5 w-9 rounded-full bg-ink-600 transition peer-checked:bg-accent-500" />
            <span className="absolute left-0.5 top-0.5 size-4 rounded-full bg-bone-100 transition peer-checked:translate-x-4 peer-checked:bg-ink-900" />
          </span>
        </label>
      </section>
    </aside>
  );
}
