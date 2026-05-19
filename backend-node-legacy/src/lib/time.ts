export function now() {
  return new Date();
}

export function normalizeText(value: string) {
  return value.trim().replace(/\s+/g, " ");
}
