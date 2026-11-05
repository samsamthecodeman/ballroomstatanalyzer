"""Windows integration checks using disposable Git remotes and a fake Docker CLI."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "scripts/Update-FromGitHub.ps1"
GIT = shutil.which("git")
POWERSHELL = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")


@unittest.skipUnless(os.name == "nt" and GIT, "Requires Windows PowerShell and Git")
class AutoDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bsa deploy ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.work = self.root / "deployment"
        self.author = self.root / "author"
        self.git(self.root, "init", "--bare", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.work))
        self.git(self.work, "checkout", "-b", "main")
        self.configure(self.work)
        (self.work / ".gitignore").write_text("tmp/\n.env\n", encoding="utf-8")
        (self.work / "app.txt").write_text("Initial version", encoding="utf-8")
        self.commit(self.work)
        self.git(self.work, "push", "-u", "origin", "main")
        self.initial = self.git(self.work, "rev-parse", "HEAD").strip()
        (self.work / ".env").write_text("TEST_ONLY=true", encoding="utf-8")
        self.stamp = self.work / "tmp/auto-deploy/deployed-commit.txt"
        self.stamp.parent.mkdir(parents=True)
        self.stamp.write_text(self.initial, encoding="ascii")
        self.git(self.root, "clone", "-b", "main", str(self.remote), str(self.author))
        self.configure(self.author)
        self.docker = self.root / "fake-docker.cmd"
        self.calls = self.root / "docker-calls.log"
        self.docker.write_text('@echo off\r\necho %*>>"%~dp0docker-calls.log"\r\n'
                               'if "%~1 %~2"=="compose build" if exist "%~dp0fail-build" exit /b 1\r\n'
                               'echo fake docker success\r\nexit /b 0\r\n', encoding="ascii")

    def git(self, directory, *args):
        return subprocess.run([GIT, "-C", str(directory), *args], check=True, capture_output=True, text=True).stdout

    def configure(self, directory):
        self.git(directory, "config", "user.name", "Deployment Test")
        self.git(directory, "config", "user.email", "test@example.com")

    def commit(self, directory):
        self.git(directory, "add", ".")
        self.git(directory, "commit", "-m", "Test revision")

    def new_remote_revision(self):
        (self.author / "app.txt").write_text("Updated version", encoding="utf-8")
        self.commit(self.author)
        self.git(self.author, "push", "origin", "main")
        return self.git(self.author, "rev-parse", "HEAD").strip()

    def update(self, *args, expected=0):
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(SCRIPT), "-ProjectPath", str(self.work), "-GitPath", GIT,
                                 "-DockerPath", str(self.docker), *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def test_unchanged_commit_does_not_rebuild(self):
        self.assertIn("No update needed", self.update())
        self.assertFalse(self.calls.exists())

    def test_dirty_worktree_is_preserved(self):
        (self.work / "app.txt").write_text("Uncommitted edit", encoding="utf-8")
        self.assertIn("Skipped: uncommitted", self.update())
        self.assertEqual((self.work / "app.txt").read_text(), "Uncommitted edit")
        self.assertFalse(self.calls.exists())

    def test_check_only_does_not_pull_or_deploy(self):
        self.new_remote_revision()
        self.assertIn("Check-only", self.update("-CheckOnly"))
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD").strip(), self.initial)
        self.assertFalse(self.calls.exists())

    def test_new_commit_builds_and_waits_for_health_once(self):
        revision = self.new_remote_revision()
        self.assertIn("Deployment succeeded", self.update())
        self.assertEqual(self.stamp.read_text().strip(), revision)
        self.assertIn("compose up -d --no-deps --wait --wait-timeout 120 app", self.calls.read_text())
        calls = self.calls.read_text()
        self.update()
        self.assertEqual(self.calls.read_text(), calls)
        self.assertEqual((self.work / ".env").read_text(), "TEST_ONLY=true")

    def test_failed_build_is_retried_without_marking_deployed(self):
        revision = self.new_remote_revision()
        failure = self.root / "fail-build"
        failure.touch()
        self.update(expected=1)
        self.assertEqual(self.stamp.read_text().strip(), self.initial)
        self.assertNotIn("compose up", self.calls.read_text())
        failure.unlink()
        self.assertIn("Deployment succeeded", self.update())
        self.assertEqual(self.stamp.read_text().strip(), revision)

    def test_divergent_history_is_not_reset(self):
        self.new_remote_revision()
        (self.work / "local.txt").write_text("Local commit", encoding="utf-8")
        self.commit(self.work)
        local = self.git(self.work, "rev-parse", "HEAD").strip()
        self.update(expected=1)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD").strip(), local)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
