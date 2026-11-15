// Where the pages fetch files that live in the Cloudflare R2 bucket instead of
// git (config/r2.json, docs/r2.md): the per-person files of the Feedback Index
// and Review Load, and the Feedback Index's comment download. Files are named by
// the person's normalised address (feedback.ts `personFile`): the bucket can't be
// listed, so a person's file is found only by typing their address.
import config from '../../config/r2.json';

/** The bucket's prefixes, as config/r2.json names them. A prefix carries the
 * files' format version (people/v2): weekly data is rewritten under the same
 * names, and only a change this code can't read moves to a new prefix. */
export const FEEDBACK_PEOPLE = 'review-feedback/people/v2';
export const LOAD_PEOPLE = 'review-load/people/v2';
export const THREADS = 'review-feedback/threads/v3';

for (const p of [FEEDBACK_PEOPLE, LOAD_PEOPLE, THREADS]) {
  if (!(p in config.prefixes)) throw new Error(`${p}: not in config/r2.json`);
}

/** Pages served from this machine (`npm run serve`, `npm run dev`, the tests) read
 * the local copies, which Vite serves under r2/ (web/vite.config.ts), so new
 * files can be checked before they are uploaded; the site reads the bucket. */
export function r2Base(host: string = location.hostname): string {
  return host === 'localhost' || host === '127.0.0.1' ? 'r2/' : config.public_base;
}

/** A file's path under its prefix: a person's file (web/vite.config.ts serves the same). */
export const R2_PATH = /^[a-z0-9._~-]+@[a-z0-9._@~-]+\.json$/;

/** The URL of one file under a prefix; `v` (the data's end, or another stamp
 * that changes with the data) makes each update a new cache key. */
export function r2Url(prefix: string, path: string, v: string | number, host?: string): string {
  if (!R2_PATH.test(path)) throw new Error(`bad R2 path ${path}`);
  return `${r2Base(host)}${prefix}/${path}?v=${typeof v === 'number' ? Math.trunc(v) : encodeURIComponent(v)}`;
}
