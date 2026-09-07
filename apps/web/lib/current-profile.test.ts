import { describe, expect, it } from "vitest";
import { currentProfileHref } from "./current-profile";

describe("current profile navigation", () => {
  it("links only an exact published current identity", () => {
    expect(currentProfileHref("province", "it:province:057", "057", ["it:province:057"])).toBe("/territori/province/057");
  });

  it("does not map a historical Province/UTS identity to a current profile", () => {
    expect(currentProfileHref("province", "it:province:215", "215", ["it:province:015"])).toBeUndefined();
  });

  it("keeps the current municipality route unchanged", () => {
    expect(currentProfileHref("municipality", "it:municipality:057001", "057001", ["it:municipality:057001"])).toBe("/territori/comuni/057001");
  });
});
