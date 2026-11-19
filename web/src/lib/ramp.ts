/**
 * A gain parameter whose automation we model ourselves.
 *
 * Reading `AudioParam.value` during a ramp is not reliable across browsers, and the main thread
 * cannot see the audio thread's exact state anyway. To retarget a fade mid-ramp without a jump we
 * keep our own record of the one linear segment we scheduled and compute the value from it.
 */

/** The subset of AudioParam this module uses, so tests can pass a fake. */
export interface ParamLike {
  setValueAtTime(value: number, time: number): unknown;
  linearRampToValueAtTime(value: number, time: number): unknown;
  cancelScheduledValues(time: number): unknown;
  /** Not in every browser (Firefox lacks it); used when present. */
  cancelAndHoldAtTime?(time: number): unknown;
}

export interface Segment {
  from: number;
  to: number;
  t0: number;
  t1: number;
}

/** Value of a linear segment at time t: holds `from` before t0 and `to` after t1. */
export function segmentValueAt(seg: Segment, t: number): number {
  if (t <= seg.t0) return seg.from;
  if (t >= seg.t1 || seg.t1 <= seg.t0) return seg.to;
  const x = (t - seg.t0) / (seg.t1 - seg.t0);
  return seg.from + (seg.to - seg.from) * x;
}

export class RampedParam {
  private seg: Segment;

  constructor(
    private readonly param: ParamLike,
    initial: number,
    now: number,
  ) {
    this.seg = { from: initial, to: initial, t0: now, t1: now };
    param.cancelScheduledValues(now);
    param.setValueAtTime(initial, now);
  }

  valueAt(t: number): number {
    return segmentValueAt(this.seg, t);
  }

  get target(): number {
    return this.seg.to;
  }

  /**
   * Ramp linearly from wherever the parameter is at `now` to `target` over `duration` seconds.
   * Starting from the modelled current value is what keeps a reversal mid-fade free of steps.
   */
  rampTo(target: number, now: number, duration: number): void {
    const from = this.valueAt(now);
    // cancelScheduledValues alone would drop the running ramp and snap the parameter back to the
    // ramp's start value until the next event; holding first (or setting `from` at once) avoids it.
    if (this.param.cancelAndHoldAtTime) this.param.cancelAndHoldAtTime(now);
    else this.param.cancelScheduledValues(now);
    this.param.setValueAtTime(from, now);
    if (duration > 0) {
      this.param.linearRampToValueAtTime(target, now + duration);
    } else {
      this.param.setValueAtTime(target, now);
    }
    this.seg = { from, to: target, t0: now, t1: now + Math.max(0, duration) };
  }
}
