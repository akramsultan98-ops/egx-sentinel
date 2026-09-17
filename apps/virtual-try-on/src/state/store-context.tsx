'use client';

import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore } from 'react';

import { DEFAULT_FILTERS, type CatalogFilters, type Product, productById } from '@/data/catalog';
import { createSessionStore } from '@/lib/session-store';

/**
 * Storefront state: bag, wishlist and catalogue filters.
 *
 * Bag and wishlist survive a refresh via sessionStorage; filters are
 * deliberately transient. A production deployment swaps the two stores for the
 * host commerce platform's cart — the fitting room only depends on `addToBag`.
 */

export interface BagLine {
  productId: string;
  colorId: string;
  size: string;
  quantity: number;
}

const bagStore = createSessionStore<BagLine[]>('vto.bag', []);
const wishlistStore = createSessionStore<string[]>('vto.wishlist', []);

interface StoreValue {
  bag: BagLine[];
  bagCount: number;
  bagTotal: number;
  wishlist: string[];
  filters: CatalogFilters;
  bagOpen: boolean;
  addToBag(product: Product, options?: { colorId?: string; size?: string }): void;
  removeFromBag(line: BagLine): void;
  setBagOpen(open: boolean): void;
  toggleWishlist(productId: string): void;
  setFilters(update: Partial<CatalogFilters>): void;
  resetFilters(): void;
}

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const bag = useSyncExternalStore(bagStore.subscribe, bagStore.getSnapshot, bagStore.getServerSnapshot);
  const wishlist = useSyncExternalStore(
    wishlistStore.subscribe,
    wishlistStore.getSnapshot,
    wishlistStore.getServerSnapshot,
  );

  const [filters, setFiltersState] = useState<CatalogFilters>(DEFAULT_FILTERS);
  const [bagOpen, setBagOpen] = useState(false);

  const addToBag = useCallback<StoreValue['addToBag']>((product, options) => {
    const colorId = options?.colorId ?? product.colors[0]?.id ?? 'default';
    const size = options?.size ?? product.sizes[Math.floor(product.sizes.length / 2)] ?? 'One size';

    bagStore.set((current) => {
      const index = current.findIndex(
        (line) => line.productId === product.id && line.colorId === colorId && line.size === size,
      );
      if (index === -1) return [...current, { productId: product.id, colorId, size, quantity: 1 }];
      const next = [...current];
      next[index] = { ...next[index], quantity: next[index].quantity + 1 };
      return next;
    });
    setBagOpen(true);
  }, []);

  const removeFromBag = useCallback<StoreValue['removeFromBag']>((line) => {
    bagStore.set((current) =>
      current.filter(
        (item) =>
          !(item.productId === line.productId && item.colorId === line.colorId && item.size === line.size),
      ),
    );
  }, []);

  const toggleWishlist = useCallback((productId: string) => {
    wishlistStore.set((current) =>
      current.includes(productId) ? current.filter((id) => id !== productId) : [...current, productId],
    );
  }, []);

  const setFilters = useCallback((update: Partial<CatalogFilters>) => {
    setFiltersState((current) => ({ ...current, ...update }));
  }, []);

  const resetFilters = useCallback(() => setFiltersState(DEFAULT_FILTERS), []);

  const value = useMemo<StoreValue>(() => {
    const bagCount = bag.reduce((total, line) => total + line.quantity, 0);
    const bagTotal = bag.reduce(
      (total, line) => total + (productById(line.productId)?.price ?? 0) * line.quantity,
      0,
    );
    return {
      bag,
      bagCount,
      bagTotal,
      wishlist,
      filters,
      bagOpen,
      addToBag,
      removeFromBag,
      setBagOpen,
      toggleWishlist,
      setFilters,
      resetFilters,
    };
  }, [bag, wishlist, filters, bagOpen, addToBag, removeFromBag, toggleWishlist, setFilters, resetFilters]);

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const value = useContext(StoreContext);
  if (!value) throw new Error('useStore must be used inside <StoreProvider>');
  return value;
}
