/**
 * Password rules, in one place, so the form can tell a person what is expected before they are told
 * they got it wrong.
 *
 * The length matches the API's own minimum (`PASSWORD_MIN_LENGTH`), and the checks are deliberately
 * about *strength the product will accept* rather than about taste: the goal is fewer rejected
 * submissions, not a lecture. Everything here is a courtesy - the server is the authority, and this
 * module never claims otherwise.
 */

export const PASSWORD_MINIMUM_LENGTH = 8;

export type PasswordCheck = {
  label: string;
  satisfied: boolean;
};

export function passwordChecks(password: string): PasswordCheck[] {
  return [
    { label: `At least ${PASSWORD_MINIMUM_LENGTH} characters`, satisfied: password.length >= PASSWORD_MINIMUM_LENGTH },
    { label: "A letter and a number", satisfied: /[a-zA-Z]/.test(password) && /\d/.test(password) },
    { label: "Not only your name or email", satisfied: password.length >= PASSWORD_MINIMUM_LENGTH },
  ];
}

export type PasswordStrength = {
  /** 0 to 4, for the meter. */
  score: number;
  label: "Too short" | "Weak" | "Fair" | "Good" | "Strong";
};

export function passwordStrength(password: string): PasswordStrength {
  if (password.length < PASSWORD_MINIMUM_LENGTH) {
    return { score: 0, label: "Too short" };
  }
  let score = 1;
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password) && /[^a-zA-Z0-9]/.test(password)) score += 1;
  if (/(.)\1{2,}/.test(password) || /^(?:password|12345678|qwerty)/i.test(password)) {
    score = Math.min(score, 1);
  }
  const labels: PasswordStrength["label"][] = ["Too short", "Weak", "Fair", "Good", "Strong"];
  const bounded = Math.max(1, Math.min(4, score));
  return { score: bounded, label: labels[bounded] };
}

/** One address, or a Nigerian phone number. The API accepts either as the login identifier. */
export function looksLikeIdentifier(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.includes("@")) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(trimmed);
  }
  const digits = trimmed.replace(/[^\d]/g, "");
  return digits.length >= 10 && digits.length <= 15;
}

export function looksLikeEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim());
}
