import { describe, expect, it } from "vitest";
import { _setPayload, has, pluralForm, t, tn } from "./i18n";

const payload = {
  default: "pl",
  languages: {
    pl: {
      name: "Polski",
      strings: {
        "home.rating": "Twój ranking: {rating}",
        "demo.cut.one": "pomijam {n} gałąź",
        "demo.cut.few": "pomijam {n} gałęzie",
        "demo.cut.many": "pomijam {n} gałęzi",
        "only.pl": "tylko po polsku",
      },
    },
    en: {
      name: "English",
      strings: {
        "home.rating": "Your rating: {rating}",
        "demo.cut.one": "skipping {n} branch",
        "demo.cut.many": "skipping {n} branches",
      },
    },
  },
};

describe("tłumaczenia", () => {
  it("wstawia parametry jak str.format w Pythonie", () => {
    _setPayload(payload, "pl");
    expect(t("home.rating", { rating: 1500 })).toBe("Twój ranking: 1500");
    expect(t("home.rating")).toBe("Twój ranking: {rating}");
  });

  it("brakujący klucz bierze z języka domyślnego, a nieznany zwraca sam klucz", () => {
    _setPayload(payload, "en");
    expect(t("only.pl")).toBe("tylko po polsku");
    expect(t("no.such.key")).toBe("no.such.key");
    expect(has("home.rating")).toBe(true);
  });

  it("napisy samego interfejsu (ustawienia) są w obu językach", () => {
    _setPayload(payload, "pl");
    expect(t("ui.fps_counter")).toBe("Licznik FPS");
    _setPayload(payload, "en");
    expect(t("ui.fps_counter")).toBe("FPS counter");
  });

  it("liczba mnoga jak w Pythonie (1 / 2–4 / 5+, ale 12–14 → many)", () => {
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
