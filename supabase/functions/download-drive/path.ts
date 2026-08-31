export function downloadDriveSubpath(pathname: string): string {
  for (const slug of ["download-drive-staging", "download-drive"]) {
    const marker = `/${slug}`;
    const index = pathname.indexOf(marker);
    if (index < 0) continue;
    const after = pathname.slice(index + marker.length);
    if (after === "" || after.startsWith("/")) return after || "/";
  }
  return "/";
}

export function downloadMcpServiceForDrive(pathname: string): string {
  return pathname.includes("/download-drive-staging")
    ? "download-mcp-staging"
    : "download-mcp";
}

export function escapeDriveQueryLiteral(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

export { normalizeDestination } from "../_shared/download_path.ts";

