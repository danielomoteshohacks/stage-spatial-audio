import { describe, expect, it } from "vitest";
import { forcedTheme, isChoice, resolveTheme, THEME_COLOR } from "./theme";
import { hashTint } from "./tint";

describe("theme", () => {
  it("is light unless asked, follows the system on 'system', and obeys an explicit choice", () => {
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
  it("accepts only known choices and a forced theme from the address", () => {
    expect(isChoice("dark")).toBe(true);
    expect(isChoice("sepia")).toBe(false);
    expect(forcedTheme("?theme=dark")).toBe("dark");
    expect(forcedTheme("?theme=neon")).toBeNull();
    expect(forcedTheme("")).toBeNull();
  });
  it("has a browser colour for each theme", () => {
    expect(THEME_COLOR.light).not.toBe(THEME_COLOR.dark);
  });
  it("tints a track the same way every time and differently from another", () => {
    expect(hashTint("jamendo:1")).toEqual(hashTint("jamendo:1"));
    expect(hashTint("jamendo:1")).not.toEqual(hashTint("jamendo:2"));
  });
});
