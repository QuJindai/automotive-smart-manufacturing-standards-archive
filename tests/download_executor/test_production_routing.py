from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "download-executor.yml"


class DownloadProductionRoutingContracts(unittest.TestCase):
    def test_executor_uses_production_control_plane(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("/functions/v1/download-mcp/executor/job/$DOWNLOAD_ID", text)
        self.assertIn("else 'download-mcp'", text)
        self.assertIn("download-mcp-large-result", text)
        self.assertNotIn("download-mcp-staging/executor/", text)

    def test_executor_uses_production_drive_gateway_and_verifies_direct_uploads(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("/functions/v1/download-drive'", text)
        self.assertIn("/functions/v1/download-drive/executor/verify/$DOWNLOAD_ID", text)
        self.assertIn("data['drive_verified']=True", text)
        self.assertNotIn("/functions/v1/download-drive-staging", text)

    def test_staging_acceptance_remains_explicitly_staging(self):
        staging = (
            ROOT / ".github" / "workflows" / "download-plugin-staging-acceptance.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("download-mcp-staging", staging)
        drive_staging = (
            ROOT / ".github" / "workflows" / "download-drive-staging-acceptance.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("download-drive-staging", drive_staging)


if __name__ == "__main__":
    unittest.main()
