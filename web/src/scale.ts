// The value-ratio axis: parity (1.0) sits in the vertical middle. The lower
// half is linear from 0 to 1; the upper half is linear from 1 to `upper`
// (a rounded-up maximum). Chart.js plots the transformed value on a plain
// 0..2 linear axis, and tick labels / tooltips map back to ratios.

export interface PivotScale {
  /** Ratio at the top of the axis. */
  upper: number;
  /** Tick spacing in the upper half, in ratio units. */
  upperStep: number;
  /** Tick positions in ratio units, ascending, including 0, 1 and upper. */
  ticks: number[];
  toAxis(ratio: number): number;
  fromAxis(axis: number): number;
}

export const AXIS_MIN = 0;
export const AXIS_MID = 1;
export const AXIS_MAX = 2;

const LOWER_TICKS = [0, 0.25, 0.5, 0.75, 1];
const MAX_UPPER_TICKS = 4;

/** 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, ... */
function* niceSteps(): Generator<number> {
  yield 0.25;
  yield 0.5;
  for (let p = 1; ; p *= 10) {
    yield p;
    yield 2 * p;
    yield 2.5 * p;
    yield 5 * p;
  }
}

export function pivotScale(maxRatio: number): PivotScale {
  // 5% headroom so the top point never sits on the frame; always show at
  // least one step above parity.
  const target = Math.max(Number.isFinite(maxRatio) ? maxRatio * 1.05 : 0, 1.25);
  const span = target - 1;
  let upperStep = 0.25;
  let n = 1;
  for (const step of niceSteps()) {
    n = Math.ceil(span / step - 1e-9);
    if (n <= MAX_UPPER_TICKS) {
      upperStep = step;
      break;
    }
  }
  const upper = 1 + n * upperStep;
  const ticks = [...LOWER_TICKS];
  for (let i = 1; i <= n; i++) ticks.push(1 + i * upperStep);

  return {
    upper,
    upperStep,
    ticks,
    toAxis: (r) => (r <= 1 ? r : 1 + (r - 1) / (upper - 1)),
    fromAxis: (y) => (y <= 1 ? y : 1 + (y - 1) * (upper - 1)),
  };
}

export function formatRatio(r: number): string {
  if (r === 0) return '0';
  if (r >= 10) return r.toFixed(0);
  return r.toFixed(2).replace(/0$/, '');
}
