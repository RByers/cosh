import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Relative asset URLs, so the site works from any GitHub Pages path.
  base: './',
  // Data files live outside web/ (summaries/, data/public/, config/).
  server: { fs: { allow: ['..'] } },
  build: { outDir: 'dist', emptyOutDir: true, assetsInlineLimit: 0 },
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    // Shared machine: never more than 4 test workers (see ~/.claude/CLAUDE.md).
    maxWorkers: 4,
    // Browser tests start one headless Chrome per file; keep files serial.
    fileParallelism: false,
    testTimeout: 30_000,
    hookTimeout: 60_000,
  },
});
