export function normalizeDestination(value: unknown): string[] {
  if (value == null || String(value).trim() === "") return [];
  const raw = String(value).trim();
  if (/^(?:[A-Za-z]:[\\/]|[\\/])/.test(raw)) {
    throw new Error("absolute Drive destination rejected");
  }
  let parts = raw.split(/[\\/]+/).map((part) => part.trim()).filter(Boolean);
  while (/^(?:google drive|下载)$/i.test(parts[0] ?? "")) parts = parts.slice(1);
  parts = parts.filter((part) => part !== ".");
  if (parts.some((part) => part === "..")) {
    throw new Error("Drive destination traversal rejected");
  }
  if (parts.some((part) => /[\u0000-\u001f\u007f]/.test(part))) {
    throw new Error("Drive destination control character rejected");
  }
  if (parts.some((part) => part.length > 100)) {
    throw new Error("Drive destination segment too long");
  }
  if (parts.length > 8) throw new Error("Drive destination depth exceeded");
  return parts;
}

export function canonicalDestination(value: unknown): string {
  const parts = normalizeDestination(value);
  return parts.length ? `Google Drive/下载/${parts.join("/")}` : "Google Drive/下载";
}

