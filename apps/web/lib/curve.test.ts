import { describe, expect, it } from "vitest";

import { pickOffset, survivalPolyline, valuePolyline } from "./curve";

const BOX = { width: 100, height: 50 };

describe("valuePolyline", () => {
  it("anchors rank 1 at the left edge and the deepest rank at the right", () => {
    const points = valuePolyline(
      [
        { rank: 1, vor: 100 },
        { rank: 3, vor: 0 },
      ],
      { ...BOX, maxRank: 3, minVor: 0, maxVor: 100 },
    );
    expect(points.split(" ")[0]).toBe("0.00,0.00");
    expect(points.split(" ")[1]).toBe("100.00,50.00");
  });

  it("returns an empty string for no points so the SVG renders nothing", () => {
    expect(valuePolyline([], { ...BOX, maxRank: 5, minVor: 0, maxVor: 1 })).toBe("");
  });

  it("does not divide by zero when every VOR is identical", () => {
    const points = valuePolyline(
      [
        { rank: 1, vor: 7 },
        { rank: 2, vor: 7 },
      ],
      { ...BOX, maxRank: 2, minVor: 7, maxVor: 7 },
    );
    expect(points).not.toContain("NaN");
  });
});

describe("survivalPolyline", () => {
  it("maps survival 1 to the top and 0 to the bottom", () => {
    const points = survivalPolyline(
      [
        { pick: 10, survival: 1 },
        { pick: 20, survival: 0 },
      ],
      { ...BOX, minPick: 10, maxPick: 20 },
    );
    expect(points).toBe("0.00,0.00 100.00,50.00");
  });

  it("does not divide by zero for a single-pick span", () => {
    const points = survivalPolyline([{ pick: 10, survival: 0.5 }], {
      ...BOX,
      minPick: 10,
      maxPick: 10,
    });
    expect(points).not.toContain("NaN");
  });
});

describe("pickOffset", () => {
  it("returns the fractional position of a pick within the range", () => {
    expect(pickOffset(15, 10, 20)).toBeCloseTo(0.5);
  });

  it("clamps below the range to 0", () => {
    expect(pickOffset(5, 10, 20)).toBe(0);
  });

  it("clamps above the range to 1", () => {
    expect(pickOffset(25, 10, 20)).toBe(1);
  });

  it("does not divide by zero for a single-pick range", () => {
    expect(pickOffset(10, 10, 10)).not.toBeNaN();
  });
});
