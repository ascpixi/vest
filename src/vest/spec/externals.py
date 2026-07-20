import os
import shutil
import subprocess

from vest.common.tooling import run_captured
from vest.spec.core import artifact_root, run
from vest.spec.types import ExternalRepoResolver

class GitRepoResolver:
    "Defines an external repository resolver that can clone git repositories."

    def __init__(self, remote: str, branch: str) -> None:
        self.remote = remote
        self.branch = branch

    def get_directory(self) -> str:
        return f"{artifact_root()}/@repo"
    
    def retrieve(self):
        if os.path.exists(self.get_directory()):
            shutil.rmtree(self.get_directory())
            
        run("git", [
            "clone",
            "--branch", self.branch,
            self.remote,
            self.get_directory(),
            "--depth", "1",
            "-c", "advice.detachedHead=false"
        ], stderr_is_stdout = True)

    def check(self) -> bool:
        if not os.path.exists(self.get_directory()):
            return True
        
        if not os.path.exists(os.path.join(self.get_directory(), ".git")):
            return True
        
        old_cwd = os.getcwd()

        try:
            os.chdir(self.get_directory())

            if subprocess.run(
                ["git", "symbolic-ref", "--quiet", "HEAD"],
                stdout = subprocess.DEVNULL,
                stderr = subprocess.DEVNULL
            ).returncode != 1:
                # This is a branch - check if there are any updates upstream
                upstream = run_captured("git rev-parse @{u}").strip()
                local = run_captured("git rev-parse @").strip()
            else:
                upstream = run_captured("git tag --points-at HEAD").strip()
                local = self.branch
        finally:
            os.chdir(old_cwd)

        return upstream != local

def git_repo(remote: str, branch: str) -> ExternalRepoResolver:
    """
    Specifies that the files of the component should be sourced by cloning a remote
    git repository.

    @remote: The location of the remote repository. Usually a URL.
    @branch: The branch to clone.
    """
    return GitRepoResolver(remote, branch)

