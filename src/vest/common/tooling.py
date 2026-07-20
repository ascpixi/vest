import subprocess

from vest.common.log import log_error
from vest.spec.types import BuildError

def run_captured(prompt: str):
    "Runs a sub-process and returns its output."

    proc = subprocess.run(
        prompt.split(" "),
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
        text = True
    )

    if proc.returncode != 0:
        log_error(f"Invocation of '{prompt}' failed with return code {proc.returncode}.")
        log_error("Captured output:")
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if stdout: log_error(stderr)
        if stderr: log_error(stdout)
        raise BuildError(f"Invocation of '{prompt}' failed with return code {proc.returncode}.")

    return proc.stdout.strip()
