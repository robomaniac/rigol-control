/* Quarto remembers tabs and reader mode in localStorage. Served reports have
 * an opaque sandbox origin, so native storage is intentionally unavailable.
 * Keep those preferences only for this document when access is denied; never
 * grant access to the bench UI's storage or change working browser storage.
 * This runs from the report head before Quarto's DOM-ready handlers.
 */
(() => {
  'use strict';
  try {
    void window.localStorage.length;
    return;
  } catch (_) {
    // The sandbox (or browser privacy policy) denies persistent storage.
  }
  const values = new Map();
  const requireArguments = (provided, required) => {
    if (provided < required) throw new TypeError('Not enough arguments');
  };
  const memoryStorage = {
    get length() { return values.size; },
    key(index) {
      requireArguments(arguments.length, 1);
      return [...values.keys()][index >>> 0] ?? null;
    },
    getItem(key) {
      requireArguments(arguments.length, 1);
      return values.get(`${key}`) ?? null;
    },
    setItem(key, value) {
      requireArguments(arguments.length, 2);
      values.set(`${key}`, `${value}`);
    },
    removeItem(key) {
      requireArguments(arguments.length, 1);
      values.delete(`${key}`);
    },
    clear() { values.clear(); },
  };
  Object.defineProperty(window, 'localStorage', {
    configurable: true, enumerable: true, value: memoryStorage,
  });
})();
