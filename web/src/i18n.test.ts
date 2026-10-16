import { describe, expect, it } from "vitest";
import { _setPayload, has, pluralForm, t, tn } from "./i18n";

const payload = {
  default: "en",
  languages: {
    pl: {
      name: "Polski",
      strings: {
        "home.rating": "Twój ranking: {rating}",
        "demo.cut.one": "pomijam {n} gałąź",
        "demo.cut.few": "pomijam {n} gałęzie",
        "demo.cut.many": "pomijam {n} gałęzi",
      },
    },
    en: {
      name: "English",
      strings: {
        "home.rating": "Your rating: {rating}",
        "demo.cut.one": "skipping {n} branch",
        "demo.cut.many": "skipping {n} branches",
        "only.en": "English only",
      },
    },
  },
};

describe("translations", () => {
  it("substitutes parameters like Python's str.format", () => {
    _setPayload(payload, "pl");
    expect(t("home.rating", { rating: 1500 })).toBe("Twój ranking: 1500");
    expect(t("home.rating")).toBe("Twój ranking: {rating}");
  });

  it("takes a missing key from the default language, and returns an unknown key as is", () => {
    _setPayload(payload, "pl");
    expect(t("only.en")).toBe("English only");
    expect(t("no.such.key")).toBe("no.such.key");
    expect(has("home.rating")).toBe(true);
  });

  it("interface-only strings (settings) exist in both languages", () => {
    _setPayload(payload, "pl");
    expect(t("ui.fps_counter")).toBe("Licznik FPS");
    _setPayload(payload, "en");
    expect(t("ui.fps_counter")).toBe("FPS counter");
  });

  it("plurals as in Python (1 / 2–4 / 5+, but 12–14 → many)", () => {
    expect(pluralForm(1, "pl")).toBe("one");
    expect(pluralForm(3, "pl")).toBe("few");
    expect(pluralForm(5, "pl")).toBe("many");
    expect(pluralForm(13, "pl")).toBe("many");
    expect(pluralForm(22, "pl")).toBe("few");
    expect(pluralForm(2, "en")).toBe("many");
    _setPayload(payload, "pl");
    expect(tn("demo.cut", 1)).toBe("pomijam 1 gałąź");
    expect(tn("demo.cut", 3)).toBe("pomijam 3 gałęzie");
    expect(tn("demo.cut", 7)).toBe("pomijam 7 gałęzi");
    _setPayload(payload, "en");
    expect(tn("demo.cut", 3)).toBe("skipping 3 branches");
  });
});
