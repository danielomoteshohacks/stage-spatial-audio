// Where every object of a v3 plan is at time t, with the same rules the renderer uses
// (stage/scene3/plan.py: object_paths): breathing by section openness, plus the eased event
// paths. This is for the stage view only; the openness cross-fade here is linear over one bar,
// where the renderer uses a raised cosine, which does not matter at the size of a dot.

export interface PlanFeed {
  ch: "L" | "R" | "M" | "C" | "Ls" | "Rs";
  az: number;
  el: number;
  weight?: number;
}
export type Keys = [number, number][];
export interface PlanEvent {
  type: "riser" | "lift" | "fill" | "throw";
  t0: number;
  t1: number;
  az: Keys;
  el: Keys;
}
export interface PlanObject3 {
  name: string;
  leaf: string;
  kind: "object" | "return";
  role: string;
  mode: string;
  az: number;
  el: number;
  dist: number;
  protected?: boolean;
  breathes?: boolean;
  feeds: PlanFeed[];
  events?: PlanEvent[];
  why?: string;
}
export interface Plan3 {
  version: 3;
  genre?: string;
  space?: string;
  hrtf?: string;
  tempo_bpm?: number;
  motion_depth?: number;
  sections?: { start_s: number; end_s: number; label: string; openness: number }[];
  stems: PlanObject3[];
  events?: PlanEvent[];
}

export function smoothstep(x: number): number {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
}

/** Offset of an eased keyframe path at t; zero outside the first and after the last key. */
export function easedPath(keys: Keys, t: number): number {
  if (!keys.length) return 0;
  for (let i = 0; i < keys.length - 1; i++) {
    const [ta, va] = keys[i];
    const [tb, vb] = keys[i + 1];
    if (t >= ta && t < tb) return va + (vb - va) * smoothstep((t - ta) / Math.max(tb - ta, 1e-6));
  }
  return t >= keys[keys.length - 1][0] ? keys[keys.length - 1][1] : 0;
}

export function opennessAt(plan: Plan3, t: number): number {
  const secs = plan.sections ?? [];
  if (!secs.length) return 0.5;
  const bar = (4 * 60) / (plan.tempo_bpm || 120);
  let cur = secs[secs.length - 1].openness;
  for (let i = 0; i < secs.length; i++) {
    if (t < secs[i].end_s) {
      cur = secs[i].openness;
      // Over the last half bar of a section and the first half bar of the next, cross-fade.
      const next = secs[i + 1];
      if (next && t > secs[i].end_s - bar / 2) {
        const f = (t - (secs[i].end_s - bar / 2)) / bar;
        cur = secs[i].openness + (next.openness - secs[i].openness) * smoothstep(f);
      }
      const prev = secs[i - 1];
      if (prev && t < secs[i].start_s + bar / 2) {
        const f = (t - (secs[i].start_s - bar / 2)) / bar;
        cur = prev.openness + (secs[i].openness - prev.openness) * smoothstep(f);
      }
      break;
    }
  }
  return cur;
}

export interface Placed {
  name: string;
  role: string;
  kind: "object" | "return";
  protected: boolean;
  /** Mean of the object's feeds, for the label. */
  az: number;
  el: number;
  dist: number;
  feeds: { az: number; el: number }[];
}

export function placeObjects(plan: Plan3, t: number): Placed[] {
  const depth = plan.motion_depth ?? 1;
  const op = opennessAt(plan, t);
  return plan.stems.map((o) => {
    let kAz = 1;
    let kEl = 1;
    if (o.breathes) {
      const k = 1 - 0.4 * depth * (1 - Math.min(1, Math.max(0, op)));
      kAz = k;
      kEl = 0.5 + 0.5 * k;
    }
    let dAz = 0;
    let dEl = 0;
    for (const ev of o.events ?? []) {
      dAz += easedPath(ev.az, t);
      dEl += easedPath(ev.el, t);
    }
    const feeds = o.feeds.map((f) => {
      const az = f.az * kAz + (f.az >= 0 || (o.mode !== "pair" && o.mode !== "upmix") ? dAz : -dAz);
      return { az: ((az + 180 + 360) % 360) - 180, el: Math.min(80, Math.max(-10, f.el * kEl + dEl)) };
    });
    const az = feeds.reduce((s, f) => s + f.az, 0) / feeds.length;
    const el = feeds.reduce((s, f) => s + f.el, 0) / feeds.length;
    return { name: o.name, role: o.role, kind: o.kind, protected: !!o.protected, az, el, dist: o.dist, feeds };
  });
}

/** Top view: azimuth 0 is straight ahead (up on screen), positive to the left. */
export function toScreen(az: number, dist: number, radius: number, maxDist = 3): [number, number] {
  const r = Math.min(1, dist / maxDist) * radius;
  const a = (az * Math.PI) / 180;
  return [-Math.sin(a) * r, -Math.cos(a) * r];
}

export const ROLE_LABELS: Record<string, string> = {
  lead_vocal: "Lead vocal",
  backing_vocal: "Backing vocals",
  kick: "Kick",
  snare: "Snare",
  bass: "Bass",
  cymbals: "Hats and cymbals",
  toms: "Toms",
  guitar: "Guitar",
  keys: "Keys",
  pad: "Pads and strings",
  fx: "Effects",
  other: "Other",
  return: "The record's reverb",
};
