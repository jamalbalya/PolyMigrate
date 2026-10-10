"""Docker sandbox runner tests; Docker is always mocked."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polymigrate.validation.runner import DockerSandboxRunner, ValidationCommand


class DockerSandboxTests(unittest.TestCase):
    def test_runs_command_with_restricted_docker_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 0, "", "")
            run_result = subprocess.CompletedProcess(["docker", "run"], 0, "passed", "")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"),                  patch("polymigrate.validation.runner.subprocess.run", side_effect=[image_check, run_result]) as run:
                result = DockerSandboxRunner().run(Path(tmp), "python:3.13", ValidationCommand("compile", ("python", "-m", "compileall", "-q", ".")))
            self.assertEqual(result.status, "PASSED")
            self.assertEqual(result.stdout, "passed")
            argv = run.call_args_list[1].args[0]
            self.assertIn("--network=none", argv)
            self.assertIn("--read-only", argv)
            self.assertIn("--cap-drop=ALL", argv)
            self.assertIn("--security-opt=no-new-privileges", argv)
            self.assertNotIn("pull", argv)
            self.assertEqual(argv[-5:], ["python", "-m", "compileall", "-q", "."])

    def test_missing_docker_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("polymigrate.validation.runner.shutil.which", return_value=None):
                result = DockerSandboxRunner().run(Path(tmp), "python:3.13", ValidationCommand("compile", ("python", "-V")))
            self.assertEqual(result.status, "BLOCKED")
            self.assertIn("not found", result.details)

    def test_missing_local_image_is_blocked_without_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 1, "", "not found")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"),                  patch("polymigrate.validation.runner.subprocess.run", return_value=image_check) as run:
                result = DockerSandboxRunner().run(Path(tmp), "python:missing", ValidationCommand("compile", ("python", "-V")))
            self.assertEqual(result.status, "BLOCKED")
            self.assertIn("no image was pulled", result.details)
            self.assertEqual(run.call_count, 1)

    def test_shell_commands_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Shell commands"):
                DockerSandboxRunner().run(Path(tmp), "python:3.13", ValidationCommand("bad", ("sh", "-c", "echo bad")))

    def test_timeout_is_reported_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 0, "", "")
            timeout = subprocess.TimeoutExpired("docker run", 1, output=b"password=secret")
            cleanup_kill = subprocess.CompletedProcess(["docker", "kill"], 0, "", "")
            cleanup_remove = subprocess.CompletedProcess(["docker", "rm"], 0, "", "")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"), \
                 patch("polymigrate.validation.runner.subprocess.run", side_effect=[image_check, timeout, cleanup_kill, cleanup_remove]) as run:
                result = DockerSandboxRunner(max_output_chars=20).run(
                    Path(tmp), "python:3.13", ValidationCommand("tests", ("python", "-m", "unittest"), 1))
            self.assertEqual(result.status, "TIMEOUT")
            self.assertNotIn("secret", result.stdout)
            self.assertEqual(run.call_count, 4)
            self.assertEqual(run.call_args_list[2].args[0][1], "kill")
            self.assertEqual(run.call_args_list[3].args[0][1], "rm")

    def test_invalid_environment_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = ValidationCommand("bad-env", ("python", "-V"), environment=(("BAD-NAME", "value"),))
            with self.assertRaisesRegex(ValueError, "environment"):
                DockerSandboxRunner().run(Path(tmp), "python:3.13", command)

    def test_invalid_image_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "image reference"):
                DockerSandboxRunner().run(Path(tmp), "--privileged", ValidationCommand("check", ("python", "-V")))

    def test_invalid_resource_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "memory/CPU"):
            DockerSandboxRunner(memory_limit="--privileged")

    def test_docker_daemon_error_is_not_misreported_as_missing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_from_inspect = subprocess.CompletedProcess(
                ["docker", "image", "inspect"], 1, "", "Cannot connect to the Docker daemon")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"), \
                 patch("polymigrate.validation.runner.subprocess.run", return_value=result_from_inspect):
                result = DockerSandboxRunner().run(Path(tmp), "python:3.13", ValidationCommand("compile", ("python", "-V")))
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("daemon or permissions", result.details)

    def test_zero_test_count_is_not_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 0, "", "")
            run_result = subprocess.CompletedProcess(["docker", "run"], 0, "", "Ran 0 tests in 0.000s\\nOK")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"), \\
                 patch("polymigrate.validation.runner.subprocess.run", side_effect=[image_check, run_result]):
                result = DockerSandboxRunner().run(
                    Path(tmp), "python:3.13",
                    ValidationCommand("unit_tests-python", ("python", "-m", "unittest", "discover", "-s", "tests")))
        self.assertEqual(result.status, "NOT_RUN")
        self.assertIn("zero executed tests", result.details)

    def test_unknown_test_count_is_marked_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 0, "", "")
            run_result = subprocess.CompletedProcess(["docker", "run"], 0, "custom runner completed", "")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"), \\
                 patch("polymigrate.validation.runner.subprocess.run", side_effect=[image_check, run_result]):
                result = DockerSandboxRunner().run(
                    Path(tmp), "node:22",
                    ValidationCommand("unit_tests-node", ("npm", "test")))
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertIn("count could not be independently confirmed", result.details)

    def test_positive_unittest_count_is_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_check = subprocess.CompletedProcess(["docker", "image", "inspect"], 0, "", "")
            run_result = subprocess.CompletedProcess(["docker", "run"], 0, "", "Ran 2 tests in 0.001s\\nOK")
            with patch("polymigrate.validation.runner.shutil.which", return_value="/usr/bin/docker"), \\
                 patch("polymigrate.validation.runner.subprocess.run", side_effect=[image_check, run_result]):
                result = DockerSandboxRunner().run(
                    Path(tmp), "python:3.13",
                    ValidationCommand("unit_tests-python", ("python", "-m", "unittest", "discover", "-s", "tests")))
        self.assertEqual(result.status, "PASSED")


if __name__ == "__main__":
    unittest.main()
