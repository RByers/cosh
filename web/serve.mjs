// `npm run serve`: build once, then keep dist/ fresh with `vite build --watch`
// and serve it with `vite preview` (argus-config/ports.md, "Rules for every
// web project"). Preview starts only after the first build succeeds, so it
// never serves a missing or stale dist/. Ctrl-C or a kill stops both. Edits
// are rebuilt within seconds: reload the page to see them (there is no hot
// reload).
//
// `vite build --watch` reads the config once and watches only the files the
// build imported, so on its own it misses new files: a new page (an .html
// file plus its `input` entry in vite.config.ts) and anything added to or
// changed in public/, which it copies only when it happens to rebuild. So
// this script watches for those and restarts the watch build, which starts
// with a full build under the config as it now is:
//
//   - vite.config.ts, package.json and tsconfig.json changing;
//   - an .html file appearing in or leaving web/ (edits to a page that is
//     already built are the watch build's own job);
//   - anything changing under public/ (after it has been quiet for a few
//     seconds, so a generator writing thousands of files causes one build).
//
// If that build can't start (say vite.config.ts doesn't parse), preview
// keeps serving the last dist/ and the build is tried again at the next
// such change. If preview exits, everything stops.
//
// The port comes from vite.config.ts: the user port 5182 for the user (no
// CLAUDECODE, or DEV_PORT=user), else a random one. Extra arguments go to
// `vite preview`.
import { spawn } from 'node:child_process';
import { existsSync, watch } from 'node:fs';
import { fileURLToPath } from 'node:url';

const webDir = fileURLToPath(new URL('.', import.meta.url));
const publicDir = fileURLToPath(new URL('public', import.meta.url));
const vite = fileURLToPath(new URL('node_modules/vite/bin/vite.js', import.meta.url));
const run = (args) => spawn(process.execPath, [vite, ...args], { cwd: webDir, stdio: 'inherit' });

/** Files in web/ whose change means the build's setup changed. */
const CONFIG_FILES = new Set(['vite.config.ts', 'package.json', 'tsconfig.json']);
/** How long the watched files must be quiet before the build restarts. */
const SETTLE_MS = 1000;
const PUBLIC_SETTLE_MS = 5000;

const children = new Set();
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  clearTimeout(pending);
  for (const child of children) child.kill('SIGTERM');
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => stop(0));

// `kill <npm's pid>` doesn't reach this script: npm exits without passing the
// signal on, and this script is reparented. Notice that and stop too.
const parent = process.ppid;
setInterval(() => {
  if (process.ppid !== parent) stop(0);
}, 1000).unref();

function startPreview(args) {
  const child = run(['preview', ...args]);
  children.add(child);
  child.on('exit', (code, signal) => {
    children.delete(child);
    if (!stopping) console.error(`serve: vite preview exited (${signal ?? code}); stopping`);
    stop(code ?? 1);
  });
}

/** The running `vite build --watch`, if any. */
let watcher = null;

function startWatch() {
  const child = run(['build', '--watch']);
  children.add(child);
  watcher = child;
  child.on('exit', (code, signal) => {
    children.delete(child);
    if (watcher === child) watcher = null;
    if (stopping) return;
    // Stopped by restartWatch() to pick up new files: start the next one.
    if (child.replaced) startWatch();
    else console.error(`serve: vite build --watch exited (${signal ?? code}); still serving the last build, and trying again when the config, the pages or public/ change`);
  });
}

let pending;
/** Restarts the watch build once the watched files have been quiet for `ms`. */
function restartWatch(why, ms) {
  if (stopping) return;
  clearTimeout(pending);
  pending = setTimeout(() => {
    console.error(`serve: ${why}; rebuilding from the current config`);
    if (!watcher) return startWatch();
    watcher.replaced = true;
    watcher.kill('SIGTERM');
  }, ms);
}

let publicWatch = null;
/** Watches public/ and everything under it. It may not exist yet (a fresh
 * checkout has none), so this is tried again whenever web/ gains an entry. */
function watchPublic() {
  if (publicWatch || !existsSync(publicDir)) return;
  try {
    publicWatch = watch(publicDir, { recursive: true }, () => restartWatch('public/ changed', PUBLIC_SETTLE_MS));
    publicWatch.on('error', () => {
      // public/ was removed: drop the watch, and pick it up if it comes back.
      publicWatch?.close();
      publicWatch = null;
    });
  } catch (e) {
    console.error(`serve: can't watch public/ (${e.message}); restart to pick up changes there`);
  }
}

function watchForNewFiles() {
  watch(webDir, (event, name) => {
    if (!name) return;
    if (CONFIG_FILES.has(name)) restartWatch(`${name} changed`, SETTLE_MS);
    // 'rename' is a file appearing or going; 'change' is an edit in place.
    else if (name.endsWith('.html') && event === 'rename') restartWatch(`${name} was added or removed`, SETTLE_MS);
    else if (name === 'public') {
      watchPublic();
      restartWatch('public/ changed', PUBLIC_SETTLE_MS);
    }
  });
  watchPublic();
}

const first = run(['build']);
children.add(first);
first.on('exit', (code, signal) => {
  children.delete(first);
  if (stopping) return;
  if (code !== 0) {
    console.error(`serve: first build failed (${signal ?? code})`);
    process.exitCode = code ?? 1;
    return;
  }
  startWatch();
  watchForNewFiles();
  startPreview(process.argv.slice(2));
});
