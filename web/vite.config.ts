import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const page = (name: string) => fileURLToPath(new URL(name, import.meta.url));

// Ports: see argus-config/ports.md. USER_PORT is forwarded to the user's laptop over SSH.
// Servers started by Claude Code (CLAUDECODE=1: tests, harnesses, an agent checking its work)
// get a random port in 20000–39999 instead, unless DEV_PORT=user hands the server to the user.
const forUser = !process.env.CLAUDECODE || process.env.DEV_PORT === 'user';
export const randomPort = () => 20000 + Math.floor(Math.random() * 20000);
const devPort = (userPort: number) =>
  forUser ? { port: userPort, strictPort: true } : { port: randomPort(), strictPort: false };

/** The Content Security Policy every built page carries (SECURITY.md,
 * "Script injection on the site"): scripts, styles and data only from the
 * site itself, and Trusted Types so the browser refuses innerHTML and other
 * HTML sinks outright. GitHub Pages can't send headers, so it is a <meta>,
 * which can't set frame-ancestors or report-uri. Only the build gets it:
 * the dev server injects CSS as inline <style> and talks over a websocket. */
export const CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  // The favicons are data: URLs.
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
  "require-trusted-types-for 'script'",
  "trusted-types 'none'",
].join('; ');

const csp = (): Plugin => ({
  name: 'cosh-csp',
  apply: 'build',
  // Right after <meta charset>, before anything the policy governs.
  transformIndexHtml(html, { filename }) {
    const charset = '<meta charset="utf-8" />';
    if (!html.includes(charset)) throw new Error(`${filename}: no ${charset} to put the CSP after`);
    return html.replace(charset, `${charset}\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
  },
});

export default defineConfig({
  plugins: [csp()],
  // Relative asset URLs, so the site works from any GitHub Pages path.
  base: './',
  server: {
    host: 'localhost',
    ...devPort(5182),
    // Data files live outside web/ (summaries/, data/public/, config/).
    fs: { allow: ['..'] },
  },
  preview: { host: 'localhost', ...devPort(5183) },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
    // One page per dashboard, plus the landing page that links to them.
    rolldownOptions: {
      input: { index: page('index.html'), value: page('value.html'), sentiment: page('sentiment.html') },
    },
  },
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
