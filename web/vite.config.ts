import { readdirSync } from 'node:fs';
import { getPriority, setPriority } from 'node:os';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

// Test runs drop their CPU priority by 5 nice levels, relative to whatever
// launched them, so they yield to interactive sessions on this shared machine
// under contention without being starved. It happens at config load so the
// workers and headless Chrome started afterwards inherit it. Linux nice is per
// thread and threads already running (vite's transform workers, libuv's pool)
// keep their own, so each is reniced; without /proc, tid 0 is the process.
// VITEST is set before vitest loads this file (`vite` and `vite build` leave it
// unset). browser.test.ts imports this file inside a worker, which has
// VITEST_WORKER_ID set and must not lower the priority a second time.
const NICE_STEP = 5;
if (process.env.VITEST && !process.env.VITEST_WORKER_ID) {
  const nice = Math.min(19, getPriority() + NICE_STEP);
  let threads = [0];
  try {
    threads = readdirSync('/proc/self/task').map(Number);
  } catch {
    // No /proc: not Linux.
  }
  for (const tid of threads) {
    try {
      setPriority(tid, nice);
    } catch {
      // Not permitted, or the thread exited: it keeps the caller's priority.
    }
  }
}

const page = (name: string) => fileURLToPath(new URL(name, import.meta.url));

// Ports: see argus-config/ports.md. USER_PORT is forwarded to the user's laptop over SSH, and
// only `vite preview` (`npm run serve`) uses it. The dev server always gets a random port in
// 20000-39999, whoever runs it: it's for agents' own checks, never for the user's browser.
// Preview started by Claude Code (CLAUDECODE=1: tests, harnesses, an agent checking its work)
// gets a random port too, unless DEV_PORT=user hands it to the user. Never use port 0: Vite
// treats it as unset and falls back to 5173, another project's user port.
const USER_PORT = 5182;
const forUser = !process.env.CLAUDECODE || process.env.DEV_PORT === 'user';
export const randomPort = () => 20000 + Math.floor(Math.random() * 20000);
const randomPortOptions = () => ({ port: randomPort(), strictPort: false });

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
    ...randomPortOptions(),
    // The dev server serves any file it's allowed to, and every account on argus can reach it
    // (SECURITY.md, "Dev servers"). So allow only what the pages import: web/ itself plus these
    // data folders, never the repo root.
    fs: {
      allow: ['.', '../summaries', '../data/public', '../config', '../scripts/sentiment_prompts'],
      // Backstops in case the allow list is widened or bypassed. Setting deny replaces Vite's
      // defaults, so they are repeated here.
      deny: [
        '.env',
        '.env.*',
        '*.{crt,pem,key,p12,pfx,cer,der}',
        '.npmrc',
        '.yarnrc.yml',
        '**/.git/**',
        'secrets*',
        '**/data/private/**',
      ],
    },
  },
  preview: { host: 'localhost', ...(forUser ? { port: USER_PORT, strictPort: true } : randomPortOptions()) },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
    // One page per dashboard, plus the landing page that links to them.
    rolldownOptions: {
      input: {
        index: page('index.html'),
        value: page('value.html'),
        sentiment: page('sentiment.html'),
        balance: page('balance.html'),
        'feedback-index': page('feedback-index.html'),
        dataflow: page('dataflow.html'),
      },
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
