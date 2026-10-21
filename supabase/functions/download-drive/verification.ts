/** Compare an executor receipt with metadata read independently from Google. */
export function verifyDriveMetadata(
  ref: Record<string, any>,
  metadata: Record<string, any>,
  expectedParent: string,
) {
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
  };
}
