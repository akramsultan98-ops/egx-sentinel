import type { GarmentLayer } from '@/lib/try-on/types';

import generated from './catalog.generated.json';

/**
 * The storefront's product model.
 *
 * The data itself comes from `catalog.generated.json`, produced by
 * `npm run assets`. Point this file at a real commerce API — Shopify,
 * commercetools, a bespoke backend — and nothing downstream changes, as long as
 * each product still carries an `image`, a `layer` and a `layerRank`.
 */

export interface ProductColor {
  id: string;
  label: string;
  hex: string;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  price: number;
  compareAtPrice?: number;
  rating: number;
  reviews: number;
  layer: GarmentLayer;
  layerRank: number;
  badge?: 'new' | 'sale';
  fabric: string;
  care: string;
  description: string;
  image: string;
  colors: ProductColor[];
  sizes: string[];
}

export interface Category {
  id: string;
  label: string;
}

export const CATEGORIES = generated.categories as Category[];
export const PRODUCTS = generated.products as Product[];
export const DEFAULT_MODEL_IMAGE = generated.defaultModel as string;

export const PRICE_BOUNDS = {
  min: Math.floor(Math.min(...PRODUCTS.map((p) => p.price)) / 10) * 10,
  max: Math.ceil(Math.max(...PRODUCTS.map((p) => p.price)) / 10) * 10,
};

export function productById(id: string): Product | undefined {
  return PRODUCTS.find((product) => product.id === id);
}

export function categoryLabel(id: string): string {
  return CATEGORIES.find((category) => category.id === id)?.label ?? id;
}

export type SortKey = 'newest' | 'price-asc' | 'price-desc' | 'rating';

export const SORT_OPTIONS: Array<{ id: SortKey; label: string }> = [
  { id: 'newest', label: 'Newest' },
  { id: 'price-asc', label: 'Price: low to high' },
  { id: 'price-desc', label: 'Price: high to low' },
  { id: 'rating', label: 'Top rated' },
];

export interface CatalogFilters {
  query: string;
  category: string;
  maxPrice: number;
  onSaleOnly: boolean;
  sort: SortKey;
}

export const DEFAULT_FILTERS: CatalogFilters = {
  query: '',
  category: 'all',
  maxPrice: PRICE_BOUNDS.max,
  onSaleOnly: false,
  sort: 'newest',
};

export function filterProducts(products: Product[], filters: CatalogFilters): Product[] {
  const query = filters.query.trim().toLowerCase();

  const filtered = products.filter((product) => {
    if (filters.category !== 'all' && product.category !== filters.category) return false;
    if (product.price > filters.maxPrice) return false;
    if (filters.onSaleOnly && !product.compareAtPrice) return false;
    if (query) {
      const haystack = `${product.name} ${product.category} ${product.fabric}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });

  const sorted = [...filtered];
  switch (filters.sort) {
    case 'price-asc':
      sorted.sort((a, b) => a.price - b.price);
      break;
    case 'price-desc':
      sorted.sort((a, b) => b.price - a.price);
      break;
    case 'rating':
      sorted.sort((a, b) => b.rating - a.rating);
      break;
    default:
      // "Newest" keeps the merchandised order the catalogue was authored in.
      break;
  }
  return sorted;
}
