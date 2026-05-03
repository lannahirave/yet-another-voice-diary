import '@testing-library/jest-dom'

if (typeof window !== 'undefined') {
  const store = new Map<string, string>()
  const testLocalStorage: Storage = {
    get length() {
      return store.size
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key)
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value))
    },
  }

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: testLocalStorage,
  })
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: testLocalStorage,
  })
}
