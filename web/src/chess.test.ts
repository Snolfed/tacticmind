import { describe, expect, it } from "vitest";
import { applyMove, arrowPath, arrowPoints, fromView, parseFen, splitAlpha, squareIndex, squareName, toView, transition, turnOf } from "./chess";
import { exactLabel, whiteShare } from "./components/EvalBar";
import { niceStep } from "./components/Charts";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

describe("squares and FEN", () => {
  it("converts square names to indices and back", () => {
    expect(squareIndex("a1")).toBe(0);
    expect(squareIndex("h8")).toBe(63);
    expect(squareIndex("e4")).toBe(28);
    expect(squareIndex("z9")).toBe(-1);
    for (let i = 0; i < 64; i++) expect(squareIndex(squareName(i))).toBe(i);
  });

  it("czyta rozstawienie z FEN", () => {
    const placement = parseFen(START);
    expect(placement.size).toBe(32);
    expect(placement.get(squareIndex("e1"))).toBe("wK");
    expect(placement.get(squareIndex("d8"))).toBe("bQ");
    expect(placement.get(squareIndex("e4"))).toBeUndefined();
    expect(turnOf(START)).toBe("white");
    expect(turnOf("8/8/8/8/8/8/8/8 b - - 0 1")).toBe("black");
  });

  it("flips the board for Black", () => {
    expect(toView(squareIndex("a1"), "white")).toEqual([0, 7]);
    expect(toView(squareIndex("a1"), "black")).toEqual([7, 0]);
    for (const orientation of ["white", "black"] as const) {
      for (let i = 0; i < 64; i++) {
        const [col, row] = toView(i, orientation);
        expect(fromView(col, row, orientation)).toBe(i);
      }
    }
  });
});

describe("tentative move (applyMove)", () => {
  it("moves a piece and captures", () => {
    const after = applyMove(parseFen("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"), "e4d5");
    expect(after.get(squareIndex("d5"))).toBe("wP");
    expect(after.has(squareIndex("e4"))).toBe(false);
    expect(after.size).toBe(3);
  });

  it("castling also moves the rook", () => {
    const after = applyMove(parseFen("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1"), "e1g1");
    expect(after.get(squareIndex("g1"))).toBe("wK");
    expect(after.get(squareIndex("f1"))).toBe("wR");
    expect(after.has(squareIndex("h1"))).toBe(false);
    const long = applyMove(parseFen("r3k3/8/8/8/8/8/8/4K3 b q - 0 1"), "e8c8");
    expect(long.get(squareIndex("d8"))).toBe("bR");
    expect(long.get(squareIndex("c8"))).toBe("bK");
  });

  it("en passant removes the pawn from the adjacent square", () => {
    const after = applyMove(parseFen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"), "e5d6");
    expect(after.get(squareIndex("d6"))).toBe("wP");
    expect(after.has(squareIndex("d5"))).toBe(false);
  });

  it("promotion turns the pawn into the chosen piece", () => {
    const after = applyMove(parseFen("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1"), "b7b8n");
    expect(after.get(squareIndex("b8"))).toBe("wN");
  });
});

describe("animation (transition)", () => {
  it("a plain move is a single slide", () => {
    const before = parseFen(START);
    const after = applyMove(before, "g1f3");
    const t = transition(before, after);
    expect(t.moves).toEqual([{ piece: "wN", from: squareIndex("g1"), to: squareIndex("f3") }]);
    expect(t.vanish).toEqual([]);
    expect(t.appear).toEqual([]);
  });

  it("capture: the piece slides, the captured one disappears", () => {
    const before = parseFen("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1");
    const t = transition(before, applyMove(before, "e4d5"));
    expect(t.moves).toHaveLength(1);
    expect(t.vanish).toEqual([{ piece: "bP", square: squareIndex("d5") }]);
  });

  it("taking back a capture: the captured piece reappears", () => {
    const before = parseFen("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1");
    const after = applyMove(before, "e4d5");
    const t = transition(after, before);
    expect(t.moves).toEqual([{ piece: "wP", from: squareIndex("d5"), to: squareIndex("e4") }]);
    expect(t.appear).toEqual([{ piece: "bP", square: squareIndex("d5") }]);
  });

  it("castling moves the king and the rook", () => {
    const before = parseFen("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1");
    const t = transition(before, applyMove(before, "e1g1"));
    expect(t.moves).toHaveLength(2);
  });

  it("promotion: the pawn slides and becomes a piece", () => {
    const before = parseFen("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1");
    const t = transition(before, applyMove(before, "b7b8q"));
    expect(t.moves).toEqual([{ piece: "wP", from: squareIndex("b7"), to: squareIndex("b8") }]);
    expect(t.appear).toEqual([]);
  });
});

describe("arrows", () => {
  it("a knight gets an L-shaped arrow", () => {
    expect(arrowPoints(squareIndex("g1"), squareIndex("f3"), "white")).toHaveLength(3);
    expect(arrowPoints(squareIndex("e2"), squareIndex("e4"), "white")).toHaveLength(2);
  });

  it("the path is a single closed polygon", () => {
    const d = arrowPath(arrowPoints(squareIndex("e2"), squareIndex("e4"), "white"), 0.2);
    expect(d.startsWith("M")).toBe(true);
    expect(d.endsWith("Z")).toBe(true);
    expect(d).not.toContain("NaN");
    const knight = arrowPath(arrowPoints(squareIndex("b1"), squareIndex("c3"), "black"), 0.2);
    expect(knight).not.toContain("NaN");
  });

  it("a knight arrow keeps its width at the bend in every direction", () => {
    // Up-then-left (g1-f3) and left-then-up (h2-f3) turns cross the ±180° angle boundary; the shaft used to swell there.
    const width = 0.18;
    for (let from = 0; from < 64; from++) {
      for (let to = 0; to < 64; to++) {
        if (arrowPoints(from, to, "white").length !== 3) continue;
        for (const orientation of ["white", "black"] as const) {
          const points = arrowPoints(from, to, orientation);
          const corner = points[1] as [number, number];
          const outline = (arrowPath(points, width).slice(1, -1).split("L")).map((p) => p.split(" ").map(Number));
          for (const index of [1, outline.length - 2]) {
            const [x, y] = outline[index] as [number, number];
            expect(Math.hypot(x - corner[0], y - corner[1])).toBeCloseTo((width / 2) * Math.SQRT2, 3);
          }
        }
      }
    }
  });

  it("splits colour and opacity", () => {
    expect(splitAlpha("rgba(45,212,191,0.84)")).toEqual(["rgb(45,212,191)", 0.84]);
    expect(splitAlpha("rgb(1, 2, 3)")).toEqual(["rgb(1,2,3)", 1]);
    expect(splitAlpha("red")).toEqual(["red", 1]);
  });
});

describe("evaluation bar and charts", () => {
  it("an evaluation of 0 is half the bar, mate is the whole bar", () => {
    expect(whiteShare({ cp: 0, mate: null, value: 0, label: "0.0" })).toBeCloseTo(0.5);
    expect(whiteShare({ cp: null, mate: 3, value: 99997, label: "M3" })).toBe(1);
    expect(whiteShare({ cp: null, mate: -2, value: -99998, label: "-M2" })).toBe(0);
    expect(whiteShare({ cp: 5000, mate: null, value: 5000, label: "+50.0" })).toBe(0.97);
  });

  it("shows the exact evaluation to two decimals under the pointer", () => {
    expect(exactLabel({ cp: 37, mate: null, value: 37, label: "+0.4" })).toBe("+0.37");
    expect(exactLabel({ cp: -120, mate: null, value: -120, label: "-1.2" })).toBe("-1.20");
    expect(exactLabel({ cp: 0, mate: null, value: 0, label: "0.0" })).toBe("0.00");
    expect(exactLabel({ cp: null, mate: -2, value: -31998, label: "-M2" })).toBe("-M2");
  });

  it("picks a \"nice\" axis step", () => {
    expect(niceStep(100)).toBe(25);
    expect(niceStep(40)).toBe(10);
    expect(niceStep(1000)).toBe(250);
  });
});
