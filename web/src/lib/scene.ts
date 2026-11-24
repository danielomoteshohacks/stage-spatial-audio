// Plan maths for the stage view, the same formulas as the backend (stage.scene.render), so what
// the screen shows is where the renderer put each object at that moment.

export interface PlanObject {
  name: string;
  source?: string;
  az: number;
  el: number;
  dist: number;
  spread: number;
  room_send: number;
  orig_blend: number;
  protected?: boolean;
  wide?: { spread: number; el: number };
  motion?: { path: "orbit" | "sway"; period_bars: number; depth: number; max_deg_per_s?: number };
}

export interface Plan {
  version?: number;
  track_id: string;
  mode: "stems" | "lite";
  genre?: string;
  space?: string;
  tempo_bpm?: number;
  first_downbeat_s?: number;
  motion_depth?: number;
  character?: string;
  sections?: { start_s: number; end_s: number; label: string; openness: number }[];
  stems: PlanObject[];
  [key: string]: unknown;
}

/** Azimuth offset of a moving object at time t (seconds), in degrees. */
export function motionOffset(plan: Plan, m: NonNullable<PlanObject["motion"]>, t: number): number {
  const period = (m.period_bars * 4 * 60) / (plan.tempo_bpm || 120);
  const phase = (t - (plan.first_downbeat_s ?? 0)) / period;
  return m.path === "orbit" ? 360 * phase : 0.5 * m.depth * Math.sin(2 * Math.PI * phase);
}

export function opennessAt(plan: Plan, t: number): number {
  const s = plan.sections?.find((x) => t >= x.start_s && t < x.end_s);
  return s?.openness ?? 0.5;
}

/** Where an object is at time t: azimuth (SOFA: positive left), elevation, distance, spread. */
export function objectAt(plan: Plan, o: PlanObject, t: number): { az: number; el: number; dist: number; spread: number } {
  const w = Math.min(1, Math.max(0, (opennessAt(plan, t) - 0.3) / 0.6));
  const spread = o.wide ? o.spread + (o.wide.spread - o.spread) * w : o.spread;
  const el = o.wide ? o.el + (o.wide.el - o.el) * w : o.el;
  const az = o.motion ? o.az + motionOffset(plan, o.motion, t) : o.az;
  return { az: ((((az + 180) % 360) + 360) % 360) - 180, el, dist: o.dist, spread };
}

/** Listener-centred cartesian position: x right, y up, z forward (for drawing). */
export function toXYZ(az: number, el: number, dist: number): [number, number, number] {
  const a = (az * Math.PI) / 180;
  const e = (el * Math.PI) / 180;
  return [-Math.sin(a) * Math.cos(e) * dist, Math.sin(e) * dist, Math.cos(a) * Math.cos(e) * dist];
}

/** Inverse of a top-down drag: a point on the floor (x right, z forward) to azimuth and distance. */
export function fromFloor(x: number, z: number): { az: number; dist: number } {
  return { az: (Math.atan2(-x, z) * 180) / Math.PI, dist: Math.max(0.3, Math.hypot(x, z)) };
}
