import os
import shutil
import subprocess
from pathlib import Path


def executable(name):
    local = Path(__file__).resolve().parent.parent / ".local-tools" / "usr" / "bin" / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    local = local.parent.parent / "sbin" / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


def run(args, timeout=20):
    command = executable(args[0])
    if not command:
        raise FileNotFoundError(f"{args[0]} is not installed")
    return subprocess.run([command, *args[1:]], capture_output=True, text=True,
                          timeout=timeout, check=False)


def required_output(args, timeout=20):
    proc = run(args, timeout)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"{args[0]} failed")
    return proc.stdout
