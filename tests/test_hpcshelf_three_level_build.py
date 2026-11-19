"""Offline build-command regression tests; never invoke a real container runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_hpcshelf_three_level.sh"
ARM = ROOT / "env/hpcshelf/arms/three-level"
BASE = ("catalog.hpcshelf.org/hpcshelf/podman-unit-base@sha256:"
        "8166b4eed4a9476a91800869042a3e1a5a8a037f09d05fafe771da06364bfad2")
FAKE = '''import json, os, sys
args = sys.argv[1:]
with open(os.environ["PODMAN_TEST_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "exists"]:
    sys.exit(int(os.environ.get("PODMAN_TEST_EXISTS", "0")))
elif args[0] == "build":
    if "--pull=never" in args:
        sys.exit("Podman 3.4: --pull expects a boolean; use --pull-never")
    sys.exit(int(os.environ.get("PODMAN_TEST_BUILD", "0")))
elif args[:2] == ["image", "inspect"]:
    fmt = args[args.index("--format") + 1]
    print("1024" if fmt == "{{.Size}}" else args[-1])
elif args[0] == "run":
    print("1" if args[-1].startswith("ls ") else "yes")
else:
    sys.exit("Unexpected runtime command: " + repr(args))
'''


class ThreeLevelBuildTests(unittest.TestCase):
    def test_exec_recipe_pins_cpu_pair_before_pyhealth(self):
        constraints = (ARM / "images/constraints-cpu.txt").read_text()
        pins = [line for line in constraints.splitlines() if line and not line.startswith("#")]
        self.assertEqual(pins, ["torch==2.7.1+cpu", "torchvision==0.22.1+cpu"])
        recipe = (ARM / "images/Containerfile.flower-exec").read_text()
        self.assertIn("--index-url https://download.pytorch.org/whl/cpu", recipe)
        self.assertIn("-r /opt/hpcshelf/constraints-cpu.txt", recipe)
        self.assertIn("-c /opt/hpcshelf/constraints-cpu.txt", recipe)
        self.assertLess(recipe.index("-r /opt/hpcshelf/constraints-cpu.txt"),
                        recipe.index('"pyhealth==2.0.1"'))
        self.assertIn('torch.version.cuda is None', recipe)
        self.assertIn('startswith("nvidia-")', recipe)
        self.assertNotIn('"torch==2.7.1"', recipe)

    def run_script(self, *args, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            fake = path / "podman"
            fake.write_text(f"#!{sys.executable}\n" + FAKE)
            fake.chmod(0o755)
            log = path / "commands.jsonl"
            env = dict(os.environ)
            for key in ("HPC_UNIT_BASE", "HPC_IMAGE_VERSION", "BASH_ENV", "ENV"):
                env.pop(key, None)
            env.update(PATH=tmp + os.pathsep + os.defpath,
                       PODMAN_TEST_LOG=str(log), **overrides)
            result = subprocess.run(["bash", str(SCRIPT), *args], env=env,
                                    capture_output=True, text=True, timeout=20)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_default_pin_reaches_both_containerfiles(self):
        result, calls = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        builds = [x for x in calls if x[0] == "build"]
        self.assertEqual(len(builds), 4)
        for index, call in enumerate(builds):
            self.assertIn(("BASE_IMAGE=" if index < 2 else "UNIT_BASE=") + BASE, call)
            self.assertIn("--pull-never", call)
            self.assertNotIn("--pull=never", call)
        for name, arg in (("exec", "BASE_IMAGE"), ("comm", "UNIT_BASE")):
            self.assertIn(f"ARG {arg}={BASE}",
                          (ARM / f"images/Containerfile.flower-{name}").read_text())

    def test_explicit_base_and_output_version_are_independent(self):
        result, calls = self.run_script(HPC_UNIT_BASE="localhost/custom:v2",
                                        HPC_IMAGE_VERSION="flower-v3")
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in (x for x in calls if x[0] == "build"):
            self.assertTrue(any(x.endswith("=localhost/custom:v2") for x in call))
            self.assertTrue(call[call.index("-t") + 1].endswith(":flower-v3"))

    def test_missing_base_does_not_build_or_pull_replacement(self):
        result, calls = self.run_script(PODMAN_TEST_EXISTS="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [["image", "exists", BASE]])
        self.assertIn("podman pull", result.stderr)

    def test_runtime_error_is_not_treated_as_missing_base(self):
        result, calls = self.run_script(PODMAN_TEST_EXISTS="125")
        self.assertEqual(result.returncode, 125)
        self.assertEqual(len(calls), 1)

    def test_build_failure_stops_before_next_role(self):
        result, calls = self.run_script(PODMAN_TEST_BUILD="17")
        self.assertEqual(result.returncode, 17)
        self.assertEqual([x[0] for x in calls], ["image", "build"])

    def test_show_bases_never_invokes_runtime(self):
        result, calls = self.run_script("--show-bases")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertIn(BASE, result.stdout)
        root = json.loads((ARM / "components/three-level-root/0.1/artifact.json").read_text())
        image = root["images"]["institution"]
        self.assertEqual(image["digest"], "sha256:" + image["archive"]["sha256"])
        self.assertIn(image["archive"]["sha256"], result.stdout)


if __name__ == "__main__":
    unittest.main()
