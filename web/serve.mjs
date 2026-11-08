// `npm run serve`: build once, then keep dist/ fresh with `vite build --watch`
// and serve it with `vite preview` (argus-config/ports.md, "Rules for every
// web project"). Preview starts only after the first build succeeds, so it
// never serves a missing or stale dist/. Ctrl-C or a kill stops both; if
// either exits, the other is stopped too. Edits are rebuilt within seconds:
// reload the page to see them (there is no hot reload).
//
// The port comes from vite.config.ts: the user port 5182 for the user (no
// CLAUDECODE, or DEV_PORT=user), else a random one. Extra arguments go to
// `vite preview`.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const webDir = fileURLToPath(new URL('.', import.meta.url));
const vite = fileURLToPath(new URL('node_modules/vite/bin/vite.js', import.meta.url));
const run = (args) => spawn(process.execPath, [vite, ...args], { cwd: webDir, stdio: 'inherit' });

const children = new Set();
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  for (const child of children) child.kill('SIGTERM');
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => stop(0));

// `kill <npm's pid>` doesn't reach this script: npm exits without passing the
// signal on, and this script is reparented. Notice that and stop too.
const parent = process.ppid;
setInterval(() => {
  if (process.ppid !== parent) stop(0);
}, 1000).unref();

function start(args) {
  const child = run(args);
  children.add(child);
  child.on('exit', (code, signal) => {
    children.delete(child);
    if (!stopping) console.error(`serve: vite ${args.join(' ')} exited (${signal ?? code}); stopping`);
    stop(code ?? 1);
  });
  return child;
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
  start(['build', '--watch']);
  start(['preview', ...process.argv.slice(2)]);
});
