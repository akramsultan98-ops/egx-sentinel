'use client';

import { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import { useFittingRoom } from '@/state/fitting-room-context';
import { useStore } from '@/state/store-context';

const NAV = ['Home', 'Shop', 'New Arrivals', 'Sale'];
const LANGUAGES = ['EN', 'FR', 'AR'];

const BRAND = process.env.NEXT_PUBLIC_STORE_NAME || 'STORE';

export function StoreHeader() {
  const { bagCount, wishlist, setBagOpen, filters, setFilters } = useStore();
  const { setOpen: setFittingRoomOpen, picks } = useFittingRoom();

  const [active, setActive] = useState('New Arrivals');
  const [language, setLanguage] = useState('EN');
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // ⌘K / Ctrl-K opens search, the shortcut the header advertises.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === 'Escape') setSearchOpen(false);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  return (
    <header className="sticky top-0 z-40 border-b border-ink-700/70 bg-ink-900/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1640px] items-center gap-3 px-4 sm:px-6 lg:px-10">
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          className="-ml-2 rounded-md p-2 text-bone-300 transition hover:text-bone-50 lg:hidden"
          aria-expanded={menuOpen}
          aria-label="Menu"
        >
          <Icon name={menuOpen ? 'close' : 'menu'} size={20} />
        </button>

        <nav className="hidden items-center gap-7 lg:flex" aria-label="Primary">
          {NAV.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setActive(item)}
              className={cn(
                'text-[11px] font-medium uppercase tracking-[0.16em] transition-colors',
                active === item ? 'text-bone-50' : 'text-bone-500 hover:text-bone-100',
              )}
            >
              {item}
            </button>
          ))}
        </nav>

        <a
          href="#main"
          className="mx-auto font-display text-[17px] font-medium tracking-[0.38em] text-bone-50 lg:absolute lg:left-1/2 lg:-translate-x-1/2"
        >
          {BRAND}
        </a>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <label className="hidden items-center gap-1.5 rounded-full border border-ink-600 px-2.5 py-1.5 text-[11px] text-bone-500 transition hover:border-ink-500 xl:flex">
            <span className="sr-only">Language</span>
            <select
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              className="cursor-pointer appearance-none bg-transparent pr-1 text-bone-300 outline-none"
            >
              {LANGUAGES.map((code) => (
                <option key={code} value={code} className="bg-ink-800">
                  {code}
                </option>
              ))}
            </select>
            <Icon name="chevron-down" size={12} />
          </label>

          {searchOpen ? (
            <div className="flex items-center gap-2 rounded-full border border-ink-600 bg-ink-800 px-3 py-1.5">
              <Icon name="search" size={15} className="text-bone-500" />
              <input
                ref={searchRef}
                value={filters.query}
                onChange={(event) => setFilters({ query: event.target.value })}
                onBlur={() => !filters.query && setSearchOpen(false)}
                placeholder="Search products"
                className="w-36 bg-transparent text-[13px] text-bone-100 outline-none placeholder:text-bone-600 sm:w-52"
                aria-label="Search products"
              />
              <button
                type="button"
                onClick={() => {
                  setFilters({ query: '' });
                  setSearchOpen(false);
                }}
                className="text-bone-600 transition hover:text-bone-100"
                aria-label="Close search"
              >
                <Icon name="close" size={14} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="flex items-center gap-2 rounded-full px-2.5 py-1.5 text-bone-500 transition hover:text-bone-100"
            >
              <Icon name="search" size={17} />
              <span className="hidden text-[13px] sm:inline">Search</span>
              <kbd className="ml-1 hidden rounded border border-ink-600 px-1.5 py-0.5 font-sans text-[10px] text-bone-600 xl:inline">
                ⌘K
              </kbd>
            </button>
          )}

          <IconButton
            label="Fitting room"
            onClick={() => setFittingRoomOpen(true)}
            badge={picks.length || undefined}
            accent
          >
            <Icon name="hanger" size={17} />
          </IconButton>

          <IconButton label="Wishlist" badge={wishlist.length || undefined}>
            <Icon name="heart" size={17} />
          </IconButton>

          <IconButton label="Account" className="hidden sm:inline-flex">
            <Icon name="user" size={17} />
          </IconButton>

          <IconButton label="Shopping bag" onClick={() => setBagOpen(true)} badge={bagCount || undefined}>
            <Icon name="bag" size={17} />
          </IconButton>
        </div>
      </div>

      {menuOpen ? (
        <nav className="animate-fade border-t border-ink-700/70 px-4 pb-4 lg:hidden" aria-label="Primary mobile">
          {NAV.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                setActive(item);
                setMenuOpen(false);
              }}
              className={cn(
                'block w-full border-b border-ink-800 py-3 text-left text-[12px] uppercase tracking-[0.16em]',
                active === item ? 'text-bone-50' : 'text-bone-500',
              )}
            >
              {item}
            </button>
          ))}
        </nav>
      ) : null}
    </header>
  );
}

function IconButton({
  children,
  label,
  onClick,
  badge,
  accent,
  className,
}: {
  children: React.ReactNode;
  label: string;
  onClick?: () => void;
  badge?: number;
  accent?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={badge ? `${label} (${badge})` : label}
      className={cn(
        'relative inline-flex size-9 items-center justify-center rounded-full transition',
        accent ? 'text-accent-500 hover:bg-accent-500/10' : 'text-bone-300 hover:text-bone-50',
        className,
      )}
    >
      {children}
      {badge ? (
        <span className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-accent-500 px-1 text-[10px] font-semibold leading-4 text-ink-900">
          {badge}
        </span>
      ) : null}
    </button>
  );
}
