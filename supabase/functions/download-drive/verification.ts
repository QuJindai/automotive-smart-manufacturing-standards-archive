export class PrivateDriveRequiredError extends Error {
  constructor() { super("personal archive requires private owner-only Drive destination and files"); }
}

/** Fail closed on absent metadata; never alter an existing user's sharing. */
export function assertPrivateDriveMetadata(metadata: Record<string, any>) {
  if (metadata.shared !== false || metadata.ownedByMe !== true || metadata.driveId ||
    !Array.isArray(metadata.permissions) || metadata.permissions.length === 0 ||
    metadata.permissions.some((p: Record<string, any>) => p.type !== "user" || p.role !== "owner")) {
    throw new PrivateDriveRequiredError();
  }
}

/** Compare an executor receipt with metadata read independently from Google. */
export function verifyDriveMetadata(
  ref: Record<string, any>,
  metadata: Record<string, any>,
  expectedParent: string,
  requirePrivate = false,
) {
  if (requirePrivate) assertPrivateDriveMetadata(metadata);
  const id = String(ref?.file_id ?? "");
  if (!id || metadata?.id !== id) throw new Error("Drive ref file_id mismatch");
  if (metadata.trashed || !Array.isArray(metadata.parents) || !metadata.parents.includes(expectedParent)) {
    throw new Error("Drive file is not in the expected destination folder");
  }
  if (!ref.name || metadata.name !== ref.name) throw new Error("Drive file name mismatch");
  const size = Number(ref.size);
  if (!Number.isSafeInteger(size) || size <= 0 || Number(metadata.size) !== size) {
    throw new Error("Drive file size mismatch");
  }
  const expected = String(ref.sha256 ?? "").toLowerCase();
  const actual = String(metadata.sha256Checksum ?? "").toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(expected)) throw new Error("Executor SHA256 missing or invalid");
  if (!/^[a-f0-9]{64}$/.test(actual)) throw new Error("Drive SHA256 checksum unavailable");
  if (actual !== expected) throw new Error("Drive file SHA256 mismatch");
  return {
    file_id: id, name: metadata.name, size,
    web_url: metadata.webViewLink ?? `https://drive.google.com/file/d/${id}/view`,
    sha256: actual, drive_sha256: actual, parents: metadata.parents,
    checksum_verified: true, checksum_method: "google_drive_sha256",
    ...(requirePrivate ? { private_verified: true } : {}),
  };
}
