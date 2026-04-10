const EMAIL_RE =
  /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;

export function isValidEmail(value: string): boolean {
  const t = value.trim();
  return t.length > 0 && EMAIL_RE.test(t);
}

export const PASSWORD_MIN_LENGTH = 8;

export function isValidPassword(value: string): boolean {
  return value.length >= PASSWORD_MIN_LENGTH;
}
