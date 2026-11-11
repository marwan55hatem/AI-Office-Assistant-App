import { describe, expect, it } from "vitest";

import { formatSize } from "@/components/download-card";
import { hoursText, periodRange } from "@/components/views/dashboard";
import { withOffset } from "@/components/views/meetings";
import { ar } from "@/lib/i18n/ar";
import { en } from "@/lib/i18n/en";
import { dir, fill, pickLocale } from "@/lib/i18n";
import { checkEmail, checkNewPassword, checkRequired, checkSame, firstProblem } from "@/lib/validate";
import { contentSecurityPolicy } from "@/proxy";

describe("form checks", () => {
  it("e-mail", () => {
    expect(checkEmail("")).toBe("required");
    expect(checkEmail("   ")).toBe("required");
    expect(checkEmail("not-an-email")).toBe("invalidEmail");
    expect(checkEmail("a@b")).toBe("invalidEmail");
    expect(checkEmail("sara@northwind.com")).toBeNull();
    expect(checkEmail(`${"x".repeat(250)}@a.co`)).toBe("invalidEmail");
  });
  it("passwords need 10 characters and must match", () => {
    expect(checkNewPassword("")).toBe("required");
    expect(checkNewPassword("ninechars")).toBe("tooShort");
    expect(checkNewPassword("tencharss!")).toBeNull();
    expect(checkSame("a", "b")).toBe("mismatch");
    expect(checkSame("a", "a")).toBeNull();
  });
  it("reports the first problem in form order", () => {
    expect(firstProblem({ name: checkRequired("x"), email: checkEmail("bad"), password: checkNewPassword("") }))
      .toEqual(["email", "invalidEmail"]);
    expect(firstProblem({ name: null })).toBeNull();
  });
});

describe("languages", () => {
  function shape(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(shape);
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).sort().map(([k, v]) => [k, shape(v)]));
    }
    return typeof value;
  }
  it("Arabic has exactly the English keys and list lengths", () => {
    expect(shape(ar)).toEqual(shape(en));
  });
  it("no empty texts", () => {
    const empty: string[] = [];
    const walk = (value: unknown, path: string) => {
      // a step without a screenshot has an empty "shot" and "alt" on purpose
      if (typeof value === "string") { if (!value.trim() && !/\.(shot|alt)$/.test(path)) empty.push(path); return; }
      if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, `${path}.${k}`));
    };
    walk(en, "en");
    walk(ar, "ar");
    expect(empty).toEqual([]);
  });
  it("chooses the language from the browser", () => {
    expect(pickLocale("ar-JO,ar;q=0.9,en;q=0.5")).toBe("ar");
    expect(pickLocale("en-GB,en;q=0.9")).toBe("en");
    expect(pickLocale("fr-FR,de;q=0.8")).toBe("en");
    expect(pickLocale("fr;q=1, ar;q=0.4")).toBe("ar");
    expect(pickLocale(null)).toBe("en");
    expect(dir("ar")).toBe("rtl");
    expect(dir("en")).toBe("ltr");
  });
  it("fills placeholders", () => {
    expect(fill("{from}–{to} of {total}", { from: 1, to: 10, total: 12 })).toBe("1–10 of 12");
    expect(fill("{missing}", {})).toBe("{missing}");
  });
});

describe("small helpers", () => {
  it("formats sizes", () => {
    expect(formatSize(2_695_528, "en")).toBe("2.7 MB");
    expect(formatSize(7_952_598_410, "en")).toBe("7.95 GB");
    expect(formatSize(500, "en")).toBe("500 B");
  });
  it("formats hours", () => {
    expect(hoursText(32.3667)).toBe("32h 22m");
    expect(hoursText(0.5)).toBe("30m");
  });
  it("period ranges", () => {
    const today = new Date(2026, 10, 11);
    expect(periodRange("7d", today)).toEqual(["2026-11-05", "2026-11-11"]);
    expect(periodRange("30d", today)).toEqual(["2026-10-13", "2026-11-11"]);
    expect(periodRange("month", today)).toEqual(["2026-11-01", "2026-11-11"]);
  });
  it("adds the UTC offset to a local date-time", () => {
    const value = withOffset("2030-01-15T10:00");
    expect(value).toMatch(/^2030-01-15T10:00:00[+-]\d\d:\d\d$/);
    expect(new Date(value).getTime()).toBe(new Date("2030-01-15T10:00").getTime());
  });
});

describe("content security policy", () => {
  it("allows only this site's scripts with the nonce, and no framing", () => {
    const csp = contentSecurityPolicy("abc123");
    expect(csp).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toMatch(/connect-src 'self' ws:\/\/localhost:8766/);
    expect(csp).not.toContain("unsafe-eval");
  });
});
