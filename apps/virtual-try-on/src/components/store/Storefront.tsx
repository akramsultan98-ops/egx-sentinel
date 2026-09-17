'use client';

import { useMemo, useState } from 'react';

import { FittingRoomPanel } from '@/components/fitting-room/FittingRoomPanel';
import { BagDrawer } from '@/components/store/BagDrawer';
import { FilterSidebar } from '@/components/store/FilterSidebar';
import { ProductCard } from '@/components/store/ProductCard';
import { QuickView } from '@/components/store/QuickView';
import { StoreHeader } from '@/components/store/StoreHeader';
import { Icon } from '@/components/ui/Icon';
import {
  CATEGORIES,
  PRODUCTS,
  SORT_OPTIONS,
  filterProducts,
  type Product,
  type SortKey,
} from '@/data/catalog';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';
import { useFittingRoom } from '@/state/fitting-room-context';
import { useStore } from '@/state/store-context';

/** New Arrivals: the storefront page the fitting room lives inside. */
export function Storefront() {
  const { filters, setFilters, wishlist, toggleWishlist, addToBag, resetFilters } = useStore();
  const { togglePick, hasPick } = useFittingRoom();

  const [quickView, setQuickView] = useState<Product | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const visible = useMemo(() => filterProducts(PRODUCTS, filters), [filters]);

  return (
    <div className="min-h-dvh page-wash">
      <StoreHeader />

      <main id="main" className="mx-auto max-w-[1640px] px-4 pb-24 pt-8 sm:px-6 lg:px-10 lg:pt-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl font-medium tracking-tight text-bone-50 sm:text-[38px]">
              New Arrivals
            </h1>
            <p className="mt-2 text-[13px] text-bone-500">
              {formatCount(visible.length, 'product')}
              {visible.length !== PRODUCTS.length ? ` of ${PRODUCTS.length}` : ''} · Autumn collection
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
              className="inline-flex items-center gap-2 rounded-lg border border-ink-600 px-3.5 py-2.5 text-[12.5px] text-bone-200 transition hover:border-ink-500 lg:hidden"
            >
              <Icon name="filter" size={15} />
              Filters
            </button>

            <label className="relative inline-flex items-center">
              <span className="sr-only">Sort products</span>
              <select
                value={filters.sort}
                onChange={(event) => setFilters({ sort: event.target.value as SortKey })}
                className="cursor-pointer appearance-none rounded-lg border border-ink-600 bg-ink-850 py-2.5 pl-3.5 pr-9 text-[12.5px] text-bone-200 outline-none transition hover:border-ink-500"
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id} className="bg-ink-800">
                    {option.label}
                  </option>
                ))}
              </select>
              <Icon
                name="chevron-down"
                size={14}
                className="pointer-events-none absolute right-3 text-bone-500"
              />
            </label>
          </div>
        </div>

        <nav className="scrollarea mt-6 flex gap-2 overflow-x-auto pb-1" aria-label="Categories">
          {CATEGORIES.map((category) => (
            <button
              key={category.id}
              type="button"
              onClick={() => setFilters({ category: category.id })}
              aria-pressed={filters.category === category.id}
              className={cn(
                'shrink-0 rounded-full border px-4 py-2 text-[12px] transition',
                filters.category === category.id
                  ? 'border-accent-500 bg-accent-500/12 text-accent-300'
                  : 'border-ink-700 text-bone-400 hover:border-ink-500 hover:text-bone-100',
              )}
            >
              {category.label}
            </button>
          ))}
        </nav>

        <div className="mt-7 grid gap-6 lg:grid-cols-[250px_1fr] xl:grid-cols-[270px_1fr]">
          <FilterSidebar
            products={PRODUCTS}
            className={cn('h-fit lg:sticky lg:top-24', filtersOpen ? 'block' : 'hidden lg:block')}
          />

          {visible.length === 0 ? (
            <div className="flex min-h-[46vh] flex-col items-center justify-center gap-3 rounded-panel border border-dashed border-ink-700 text-center">
              <Icon name="search" size={24} className="text-bone-600" />
              <p className="text-[14px] text-bone-300">Nothing matches these filters.</p>
              <button
                type="button"
                onClick={resetFilters}
                className="rounded-lg border border-ink-600 px-4 py-2 text-[12.5px] text-bone-200 transition hover:border-ink-500"
              >
                Reset filters
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {visible.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  wishlisted={wishlist.includes(product.id)}
                  inFittingRoom={hasPick(product.id)}
                  onToggleWishlist={() => toggleWishlist(product.id)}
                  onToggleFittingRoom={() => togglePick(product)}
                  onAddToBag={() => addToBag(product)}
                  onQuickView={() => setQuickView(product)}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <QuickView
        product={quickView}
        inFittingRoom={quickView ? hasPick(quickView.id) : false}
        onClose={() => setQuickView(null)}
        onAddToBag={(product, options) => {
          addToBag(product, options);
          setQuickView(null);
        }}
        onTryOn={(product, options) => {
          togglePick(product, options);
          setQuickView(null);
        }}
      />

      <BagDrawer />
      <FittingRoomPanel />
    </div>
  );
}
