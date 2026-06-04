import '@testing-library/jest-dom';

// Mock react-force-graph-2d — it uses canvas APIs unavailable in jsdom
vi.mock('react-force-graph-2d', () => ({
  default: () => null,
}));

// jsdom doesn't implement ResizeObserver — stub it so components that use it don't crash
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Suppress console.error from React Router future-flags warnings in tests
const originalError = console.error;
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    const msg = String(args[0] ?? '');
    if (msg.includes('React Router') || msg.includes('Warning:')) return;
    originalError(...args);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
});
