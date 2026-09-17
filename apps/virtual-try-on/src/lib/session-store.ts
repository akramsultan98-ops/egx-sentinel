'use client';

/**
 * A tiny sessionStorage-backed external store.
 *
 * Session state cannot be read while the server renders, so it is exposed
 * through `useSyncExternalStore`: the server snapshot is the fallback, the
 * client hydrates on first subscribe, and React handles the transition. That
 * avoids the read-then-setState-in-an-effect pattern, which cascades renders.
 *
 * Swap the storage backend here to persist a shopper's state across visits.
 */

export interface SessionStore<T> {
  subscribe(listener: () => void): () => void;
  getSnapshot(): T;
  getServerSnapshot(): T;
  get(): T;
  set(next: T | ((current: T) => T)): void;
}

export function createSessionStore<T>(key: string, fallback: T): SessionStore<T> {
  let snapshot = fallback;
  let hydrated = false;
  const listeners = new Set<() => void>();

  function emit() {
    for (const listener of listeners) listener();
  }

  function hydrate() {
    hydrated = true;
    try {
      const raw = sessionStorage.getItem(key);
      if (raw === null) return;
      snapshot = JSON.parse(raw) as T;
      emit();
    } catch {
      // Unreadable or unavailable storage: keep the in-memory fallback.
    }
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      if (!hydrated) hydrate();
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      return snapshot;
    },
    getServerSnapshot() {
      return fallback;
    },
    get() {
      return snapshot;
    },
    set(next) {
      const value =
        typeof next === 'function' ? (next as (current: T) => T)(snapshot) : next;
      if (Object.is(value, snapshot)) return;
      snapshot = value;
      try {
        sessionStorage.setItem(key, JSON.stringify(value));
      } catch {
        // Quota exceeded (a large photo) or private mode: memory only.
      }
      emit();
    },
  };
}
