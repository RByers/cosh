// A review comment's tone score as a small pill, shared by the Review Tone
// and Review Feedback pages.
import { fmtNum } from './format.ts';

export const signed1 = (v: number) =>
  (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v), { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** A comment's score as a small pill: "+0.6" or "−0.8", tinted from neutral
 * toward the glowing or the grumpy colour as the score grows. */
export function scoreBadge(score: number, scale = 1, title = `Score ${signed1(score)} on a scale from −1 to +1`): HTMLElement {
  const b = document.createElement('span');
  b.textContent = signed1(score);
  b.className = 'score-badge';
  const m = Math.min(1, Math.abs(score) / scale);
  b.dataset.pole = score < 0 ? 'neg' : 'pos';
  b.style.setProperty('--mix', `${Math.round(m * 100)}%`);
  if (m > 0.6) b.classList.add('score-strong');
  b.title = title;
  return b;
}
