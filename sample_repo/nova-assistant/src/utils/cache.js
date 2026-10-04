'use strict';

/**
 * In-memory cache with per-entry time to live.
 */
class TtlCache {
  constructor(ttlMs) {
    this.ttlMs = ttlMs;
    this.entries = new Map();
  }

  get(key) {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (Date.now() > entry.expires) {
      this.entries.delete(key);
      return undefined;
    }
    return entry.value;
  }

  set(key, value) {
    this.entries.set(key, { value, expires: Date.now() + this.ttlMs });
  }
}

module.exports = { TtlCache };
