/**
 * Decide which dropped file is the original and which is the Stage render.
 * scripts/render_clip.py writes input_stereo.wav and input_stage.wav, so the name is the signal.
 */

export interface Named {
  readonly name: string;
}

export type PairResult<T extends Named> =
  | { ok: true; original: T; stage: T; guessed: boolean }
  | { ok: false; error: string };

const isStage = (f: Named) => /stage/i.test(f.name.replace(/\.[^.]+$/, ""));

export function pairFiles<T extends Named>(files: readonly T[]): PairResult<T> {
  if (files.length !== 2) {
    return {
      ok: false,
      error: `Drop exactly two files (the original and the Stage render); got ${files.length}.`,
    };
  }
  const [first, second] = files as readonly [T, T];
  const firstStage = isStage(first);
  const secondStage = isStage(second);
  if (firstStage !== secondStage) {
    return firstStage
      ? { ok: true, original: second, stage: first, guessed: false }
      : { ok: true, original: first, stage: second, guessed: false };
  }
  // Names do not tell them apart: keep the drop order and let the user swap.
  return { ok: true, original: first, stage: second, guessed: true };
}
