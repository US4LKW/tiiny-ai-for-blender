"""Run independent offline tests, optionally followed by a real Blender smoke test."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", metavar="EXECUTABLE", help="Also run blender_smoke.py with this Blender executable")
    parser.add_argument("--verbose", action="store_true", help="Print output from passing tests as well as failures")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    checks = [(p.name, [sys.executable, str(p)]) for p in sorted(root.glob("test_*.py"))]
    if args.blender:
        executable = shutil.which(args.blender) or (args.blender if Path(args.blender).is_file() else None)
        if not executable:
            parser.error("Blender executable was not found: " + args.blender)
        checks.append(("Blender registration and controls", [executable, "--background", "--factory-startup",
                                                             "--python-exit-code", "1", "--python", str(root / "blender_smoke.py")]))
    failed = []
    for name, command in checks:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        print(("PASS" if result.returncode == 0 else "FAIL") + ": " + name, flush=True)
        if result.returncode or args.verbose:
            print((result.stdout + result.stderr).strip(), flush=True)
        if result.returncode:
            failed.append(name)
    print("\n%d/%d checks passed." % (len(checks) - len(failed), len(checks)))
    print("Offline checks do not validate AI output quality on a Tiiny device.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
