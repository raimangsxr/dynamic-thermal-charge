// Node exposes a guarded localStorage global that requires a persistent file.
// Tests should use an in-memory implementation instead.
const values = new Map<string, string>();
const memoryStorage: Storage = {
  get length(): number {
    return values.size;
  },
  clear(): void {
    values.clear();
  },
  getItem(key: string): string | null {
    return values.get(String(key)) ?? null;
  },
  key(index: number): string | null {
    return Array.from(values.keys())[index] ?? null;
  },
  removeItem(key: string): void {
    values.delete(String(key));
  },
  setItem(key: string, value: string): void {
    values.set(String(key), String(value));
  },
};

Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: memoryStorage,
});
