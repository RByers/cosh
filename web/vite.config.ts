import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
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
  // The SVG favicon is a data: URL; favicon.ico and apple-touch-icon.png are 'self'.
  "img-src 'self' data:",
  // Per-person files and the comment download's threads, from the R2 bucket (config/r2.json).
  "connect-src 'self' https://cosh-data.rbyers.ca",
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

/** `vite preview` answers an unknown URL with an empty 404. GitHub Pages
 * serves 404.html instead, so preview does too: this runs after preview's
 * static files and its .html fallback (which maps /value to /value.html),
 * and lets through only .html files that exist in dist/. */
const notFound = (): Plugin => ({
  name: 'cosh-404',
  configurePreviewServer(server) {
    const dist = server.config.build.outDir;
    const root = join(server.config.root, dist);
    return () => {
      server.middlewares.use((req, res, next) => {
        const path = decodeURIComponent((req.url ?? '/').split(/[?#]/)[0]);
        const page = join(root, path);
        if (path.endsWith('.html') && page.startsWith(root) && existsSync(page)) return next();
        const notFoundPage = join(root, '404.html');
        if (!existsSync(notFoundPage)) return next();
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.end(readFileSync(notFoundPage));
      });
    };
  },
});

/** The data directory (data/private) whose folders config/r2.json uploads to the bucket:
 * COSH_DATA_DIR, else the main checkout's, also from a git worktree (as cosh/contact.py). */
function dataDir(): string {
  if (process.env.COSH_DATA_DIR) return process.env.COSH_DATA_DIR;
  const repo = fileURLToPath(new URL('..', import.meta.url));
  try {
    const common = execFileSync('git', ['-C', repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' }).trim();
    if (basename(common) === '.git') return join(dirname(common), 'data', 'private');
  } catch {
    // Not a git checkout.
  }
  return join(repo, 'data', 'private');
}

/** A file's path under its prefix, as web/src/r2.ts builds it (`R2_PATH`). */
const R2_PATH = /^((?:\d{4}H[12]\/)?[a-z0-9._~-]+@[a-z0-9._@~-]+)\.json$/;

/** Pages on localhost read the bucket's files from r2/ (web/src/r2.ts): this serves them
 * from their local folders (config/r2.json), gzipped as the bucket serves them, so new files
 * can be checked before they are uploaded. Only names of the bucket's form under its known
 * prefixes are served (the same files anyone can fetch from the bucket by name). A file not on
 * this machine is a 404, never fetched from the bucket: a local page reads only local data, so a
 * local file that is missing or stale shows up instead of being masked by the published copy.
 * Both the dev server and preview use it. */
const r2Local = (): Plugin => {
  const r2 = JSON.parse(readFileSync(new URL('../config/r2.json', import.meta.url), 'utf8')) as
    { prefixes: Record<string, string> };
  const data = dataDir();
  const serve = (middlewares: { use: (fn: (req: any, res: any, next: () => void) => void) => void }) =>
    middlewares.use((req, res, next) => {
      let path = (req.url ?? '/').split(/[?#]/)[0];
      try {
        path = decodeURIComponent(path);     // a browser may send @ as %40
      } catch {
        return next();
      }
      const prefix = Object.keys(r2.prefixes).find((p) => path.startsWith(`/r2/${p}/`));
      const m = prefix ? R2_PATH.exec(path.slice(`/r2/${prefix}/`.length)) : null;
      if (!prefix || !m) return next();
      const file = join(data, r2.prefixes[prefix], `${m[1]}.json.gz`);
      if (!existsSync(file)) {
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        res.setHeader('Cache-Control', 'no-cache');
        return res.end(`not in ${r2.prefixes[prefix]}/ of the local data directory`);
      }
      res.setHeader('Content-Type', 'application/json');
      res.setHeader('Content-Encoding', 'gzip');
      res.setHeader('Cache-Control', 'no-cache');
      res.end(readFileSync(file));
    });
  return {
    name: 'cosh-r2-local',
    // Before Vite's own middlewares; returning nothing, as a returned function would run after them.
    configureServer(server) {
      serve(server.middlewares);
    },
    configurePreviewServer(server) {
      serve(server.middlewares);
    },
  };
};

export default defineConfig({
  plugins: [csp(), notFound(), r2Local()],
  // Separate pages, not a single-page app: an unknown URL is a 404, not index.html.
  appType: 'mpa',
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
        'review-load': page('review-load.html'),
        'review-timezones': page('review-timezones.html'),
        dataflow: page('dataflow.html'),
        // Served for unknown URLs by GitHub Pages, and by preview (notFound above).
        '404': page('404.html'),
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
