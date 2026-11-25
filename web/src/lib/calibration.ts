// The head calibration game (decision 0026). Short noise bursts are played from known directions
// through each candidate head (the server renders them with the real measured filters); the
// listener taps where each one seemed to come from; the head with the smallest error and the
// fewest front-back confusions is kept on this device and sent with every render.
// The scoring is the same rule as stage.spatial.heads.select_head.

export interface Trial {
  head: string;
  az: number;
  el: number;
  answerAz: number;
  answerEl: number;
  ms: number;
}

export const DEFAULT_HEAD = "D1";
export const FB_WEIGHT = 60;
const KEY = "soundstage.head";
const LOG = "soundstage.calibration";

export function angularError(az1: number, el1: number, az2: number, el2: number): number {
  const r = Math.PI / 180;
  const c =
    Math.sin(el1 * r) * Math.sin(el2 * r) + Math.cos(el1 * r) * Math.cos(el2 * r) * Math.cos((az1 - az2) * r);
  return (Math.acos(Math.min(1, Math.max(-1, c))) * 180) / Math.PI;
}

const wrap = (a: number) => ((((a + 180) % 360) + 360) % 360) - 180;

/** The answer is the mirror of the true direction about the interaural axis, and not the truth. */
export function isFrontBack(az: number, answerAz: number, tol = 25): boolean {
  const mirror = wrap(180 - az);
  const dTrue = Math.abs(wrap(answerAz - az));
  const dMirror = Math.abs(wrap(answerAz - mirror));
  return dMirror < tol && dTrue > tol && Math.abs(Math.abs(az) - 90) > 20;
}

export function scoreTrials(trials: Trial[]): { meanError: number; frontBack: number; n: number } {
  if (!trials.length) return { meanError: Infinity, frontBack: 1, n: 0 };
  const err = trials.map((t) => angularError(t.az, t.el, t.answerAz, t.answerEl));
  const fb = trials.map((t) => (isFrontBack(t.az, t.answerAz) ? 1 : 0));
  return {
    meanError: err.reduce((a, b) => a + b, 0) / err.length,
    frontBack: fb.reduce((a: number, b: number) => a + b, 0) / fb.length,
    n: trials.length,
  };
}

export function selectHead(trials: Trial[]): { best: string; scores: Record<string, ReturnType<typeof scoreTrials>> } {
  const heads = [...new Set(trials.map((t) => t.head))];
  const scores: Record<string, ReturnType<typeof scoreTrials>> = {};
  for (const h of heads) scores[h] = scoreTrials(trials.filter((t) => t.head === h));
  const best = [...heads].sort((a, b) => {
    const sa = scores[a].meanError + FB_WEIGHT * scores[a].frontBack;
    const sb = scores[b].meanError + FB_WEIGHT * scores[b].frontBack;
    return sa - sb || Number(a !== DEFAULT_HEAD) - Number(b !== DEFAULT_HEAD);
  })[0];
  return { best: best ?? DEFAULT_HEAD, scores };
}

/** Six directions per head, spread over the sphere and avoiding the interaural axis (where front
 * and back cannot be confused), in an order that does not repeat a side twice in a row. */
export const DIRECTIONS: { az: number; el: number }[] = [
  { az: 35, el: 0 }, { az: -145, el: 0 }, { az: -30, el: 35 },
  { az: 150, el: 20 }, { az: 0, el: 0 }, { az: 180, el: 0 },
];

/** A trial order: every head hears every direction, shuffled, no head twice in a row when it can
 * be avoided. `rand` is injectable so the order is testable. */
export function trialOrder(heads: string[], rand: () => number = Math.random): { head: string; az: number; el: number }[] {
  const all = heads.flatMap((head) => DIRECTIONS.map((d) => ({ head, ...d })));
  for (let i = all.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [all[i], all[j]] = [all[j], all[i]];
  }
  for (let i = 1; i < all.length; i++) {
    if (all[i].head === all[i - 1].head) {
      const k = all.findIndex((x, idx) => idx > i && x.head !== all[i - 1].head);
      if (k > 0) [all[i], all[k]] = [all[k], all[i]];
    }
  }
  return all;
}

export function loadHead(): string {
  try {
    return localStorage.getItem(KEY) || DEFAULT_HEAD;
  } catch {
    return DEFAULT_HEAD;
  }
}

export function saveHead(head: string, trials: Trial[]): void {
  try {
    localStorage.setItem(KEY, head);
    localStorage.setItem(LOG, JSON.stringify(trials.slice(-200)));
  } catch {
    // Storage can be refused; the choice then lasts for this visit.
  }
}

export function loadTrials(): Trial[] {
  try {
    return JSON.parse(localStorage.getItem(LOG) || "[]") as Trial[];
  } catch {
    return [];
  }
}

/** The results export: one row per trial, so front-back confusion and angular error can be
 * compared before and after on willing listeners. */
export function trialsCsv(trials: Trial[], chosen: string): string {
  const head = "head,true_az,true_el,answer_az,answer_el,angular_error_deg,front_back,ms,chosen";
  const rows = trials.map((t) =>
    [t.head, t.az, t.el, t.answerAz, t.answerEl, angularError(t.az, t.el, t.answerAz, t.answerEl).toFixed(1),
      isFrontBack(t.az, t.answerAz) ? 1 : 0, Math.round(t.ms), t.head === chosen ? 1 : 0].join(","));
  return [head, ...rows].join("\n");
}
