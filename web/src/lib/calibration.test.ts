import { describe, expect, it } from "vitest";
import { angularError, isFrontBack, scoreTrials, selectHead, trialOrder, trialsCsv, DIRECTIONS, type Trial } from "./calibration";

const t = (head: string, az: number, answerAz: number, el = 0, answerEl = 0): Trial =>
  ({ head, az, el, answerAz, answerEl, ms: 1500 });

describe("calibration", () => {
  it("measures angles on the sphere", () => {
    expect(angularError(0, 0, 90, 0)).toBeCloseTo(90);
    expect(angularError(-179, 0, 179, 0)).toBeCloseTo(2);
    expect(angularError(0, 0, 0, 90)).toBeCloseTo(90);
  });

  it("finds front-back confusions and ignores the side", () => {
    expect(isFrontBack(30, 150)).toBe(true);
    expect(isFrontBack(30, 50)).toBe(false);
    expect(isFrontBack(90, 90)).toBe(false);
    expect(isFrontBack(-150, -30)).toBe(true);
  });

  it("picks the head with the smaller error and fewer confusions", () => {
    const good = [-120, -60, 30, 150].map((a) => t("H3", a, a + 8));
    const bad = [-120, -60, 30, 150].map((a) => t("D1", a, 180 - a));
    const { best, scores } = selectHead([...bad, ...good]);
    expect(best).toBe("H3");
    expect(scores.H3.frontBack).toBe(0);
    expect(scores.D1.frontBack).toBe(1);
    expect(scoreTrials([]).n).toBe(0);
  });

  it("keeps the default head on a tie", () => {
    const a = [30, 150].map((x) => t("D1", x, x + 10));
    const b = [30, 150].map((x) => t("H5", x, x + 10));
    expect(selectHead([...b, ...a]).best).toBe("D1");
  });

  it("plays every head from every direction and avoids repeating a head back to back", () => {
    const order = trialOrder(["D1", "H3", "H5"], () => 0.37);
    expect(order).toHaveLength(3 * DIRECTIONS.length);
    for (const h of ["D1", "H3", "H5"]) expect(order.filter((x) => x.head === h)).toHaveLength(DIRECTIONS.length);
    const repeats = order.filter((x, i) => i > 0 && x.head === order[i - 1].head).length;
    expect(repeats).toBeLessThanOrEqual(2);
  });

  it("exports one row per trial with the chosen head marked", () => {
    const csv = trialsCsv([t("H3", 30, 40), t("D1", 30, 150)], "H3");
    const lines = csv.split("\n");
    expect(lines[0]).toContain("front_back");
    const cols = lines[1].split(",");
    expect(cols[cols.length - 1]).toBe("1");
    expect(lines[2].split(",")[6]).toBe("1");
  });
});
