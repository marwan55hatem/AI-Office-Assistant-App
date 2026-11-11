/** Form checks shared by the browser forms (the API checks everything again). Each returns the
 *  dictionary key of the problem, or null when the value is fine. */

export const MIN_PASSWORD = 10;
export const MAX_PASSWORD = 128;

export type Problem = "required" | "invalidEmail" | "tooShort" | "mismatch" | null;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function checkRequired(value: string): Problem {
  return value.trim() ? null : "required";
}

export function checkEmail(value: string): Problem {
  if (!value.trim()) return "required";
  return EMAIL.test(value.trim()) && value.length <= 254 ? null : "invalidEmail";
}

export function checkNewPassword(value: string): Problem {
  if (!value) return "required";
  return value.length >= MIN_PASSWORD ? null : "tooShort";
}

export function checkSame(password: string, again: string): Problem {
  return password === again ? null : "mismatch";
}

/** The first problem of a form, or null: `firstProblem({email: checkEmail(e), ...})`. */
export function firstProblem<K extends string>(checks: Record<K, Problem>): [K, Exclude<Problem, null>] | null {
  for (const [field, problem] of Object.entries(checks) as [K, Problem][]) {
    if (problem) return [field, problem];
  }
  return null;
}
