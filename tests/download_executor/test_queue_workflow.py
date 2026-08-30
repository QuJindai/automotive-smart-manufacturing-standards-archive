from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/download-executor.yml").read_text(encoding="utf-8")


class QueueWorkflowContracts(unittest.TestCase):
    def test_schedule_and_manual_recovery_are_enabled(self):
        self.assertIn("cron: '*/5 * * * *'", WORKFLOW)
        self.assertIn("workflow_dispatch:", WORKFLOW)

    def test_non_push_run_claims_with_oidc_and_allows_empty_queue(self):
        self.assertIn("/download-mcp/executor/claim", WORKFLOW)
        self.assertIn("code=$(curl -sS -o claim.json -w '%{http_code}' -X POST", WORKFLOW)
        self.assertIn("if [ \"$code\" = '204' ]; then", WORKFLOW)
        self.assertIn("echo 'found=false' >> \"$GITHUB_OUTPUT\"", WORKFLOW)

    def test_descriptor_push_recovery_is_preserved(self):
        self.assertIn("git diff-tree --no-commit-id", WORKFLOW)
        self.assertIn("validate_descriptor", WORKFLOW)

    def test_execution_steps_are_guarded_by_found_output(self):
        self.assertGreaterEqual(
            WORKFLOW.count("steps.descriptor.outputs.found == 'true'"),
            8,
        )


if __name__ == "__main__":
    unittest.main()

