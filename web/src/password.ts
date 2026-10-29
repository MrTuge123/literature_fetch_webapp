// The Cognito pool's password policy (infra/litfetch_infra/api_stack.py), checked before sending.
export const PASSWORD_RULE = "At least 10 characters, with lowercase letters and digits.";
export function passwordProblem(p: string): string | null {
  if (p.length < 10) return "Password needs at least 10 characters.";
  if (!/[a-z]/.test(p)) return "Password needs a lowercase letter.";
  if (!/[0-9]/.test(p)) return "Password needs a digit.";
  return null;
}
