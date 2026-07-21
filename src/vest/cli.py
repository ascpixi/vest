import os
import subprocess
import traceback

import rich
from rich.console import Console
import rich.traceback
from rich import print

from vest.common.log import is_agent, log_error_hdr, log_success_hdr, log_warn
from vest.spec.host import StandaloneHost
from vest.spec.types import BuildError, UsageError

class VestFailure(Exception):
    pass

def vest_cli(
    *,
    path: str,
    task: str,
    parameters: dict[str, str] = {},
    load_cache: bool = True,
    console: rich.console.Console | None = None
):
    """
    Runs the Vest CLI. This is equivalent to doing `vest`, but typed. When invoking, callers are expected to handle
    the `VestFailure` exception. For normal CLI invocations, a `VestFailure` means exiting with error code 1. Error information
    is already printed when a `VestFailure` is thrown.
    """

    if not console:
        console = Console()
        rich.traceback.install()

    host = StandaloneHost(
        parameters = parameters,
        load_cache = load_cache
    )

    try:
        if os.path.isdir(path):
            path = os.path.join(path, "build.vest")

        component = host.eval_component(path)
    except Exception as ex:
        log_error_hdr("Could not evaluate the component")
        print(f"[red]  ╰─> {ex}[/]")
        print()

        console.print_exception()
        raise VestFailure()

    if not any(t.name == task for t in component.tasks):
        log_error_hdr(f"No task named '{task}'.")
        print("[red]  ╰─> The defined tasks are:[/]")

        for defined_task in component.tasks:
            if defined_task.description is not None:
                print(f"[red]        - {defined_task.name}: {defined_task.description}[/]")
            else:
                print(f"[red]        - {defined_task.name}[/]")

        raise VestFailure()

    try:
        found_task = next(x for x in component.tasks if x.name == task)
        artifacts = host.run_task(found_task)
    except Exception as ex:
        if type(ex) is UsageError:
            # A UsageError indicates that neither Vest or the components in question are at fault - the user might've e.g. not specified a
            # required parameter. In this case, we don't print the stacktrace at all.
            print(" │")
            log_error_hdr(f"Could not build [bold]{component.name}:{task}[/]")
            print(f"[red]  ╰─> {ex}[/]")
            print()
            raise VestFailure()

        # https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/rich/traceback.py#L287
        rich.traceback.Traceback.LEXERS[".vest"] = "python"

        # Skip the first two frames; which are this script and the component host
        # respectively. We only want to show the faulting components.
        if ex.__traceback__ is not None:
            first = ex.__traceback__
            for i in range(2):
                if ex.__traceback__.tb_next is None:
                    ex.__traceback__ = first # revert back to the previous state
                    break

                ex.__traceback__ = ex.__traceback__.tb_next

            # A BuildError indicates that the cause of the error is incorrect usage of the
            # component system (as opposed to e.g. a bug). In this case, we don't need to
            # show the frames that belong to the component system.
            if type(ex) is BuildError:
                # Filter out stacktraces that are not .vest files (unless it's the last one)
                prev = ex.__traceback__
                current = prev.tb_next
                while current is not None and current.tb_next is not None:
                    if not current.tb_frame.f_code.co_filename.endswith(".vest"):
                        prev.tb_next = current.tb_next
                        current = prev.tb_next
                    else:
                        prev = current
                        current = current.tb_next

                # Don't show the last frame
                current = ex.__traceback__
                prev = None

                while current.tb_next is not None:
                    prev = current
                    current = current.tb_next

                if prev is not None:
                    prev.tb_next = None

        print(" │")
        log_error_hdr(f"Could not build [bold]{component.name}:{task}[/]")
        print(f"[red]  ╰─> {ex}[/]")
        print()

        if type(ex) is subprocess.CalledProcessError:
            stdout = ex.stdout.decode("utf-8") if type(ex.stdout) is bytes else str(ex.stdout)
            stderr = ex.stderr.decode("utf-8") if type(ex.stderr) is bytes else str(ex.stderr)

            stdout = stdout.strip()
            stderr = stderr.strip()
    
            if stdout:
                print(f"[red]Standard output:[/]")
                print(stdout)
                print()

            if stderr:
                print(f"[red]Standard error:[/]")
                print(stderr)
                print()

        if not is_agent():
            console.print_exception()
        else:
            traceback.print_exc()

        print()
        raise VestFailure()

    print(" │")
    log_success_hdr(f"Component [bold]{component.name}:{task}[/] built successfully")

    if type(artifacts) is str:
        print(f"  ╰─> You may find the resulting artifact in [bold]{artifacts}[/].")
    elif type(artifacts) is list:
        print(f"  ╰─> The following artifacts have been created:")

        for entry in artifacts:
            print(f"        - {entry}")
    elif type(artifacts) is dict:
        print(f"  ╰─> The following named artifacts have been created:")

        for (k, v) in artifacts.items():
            print(f"        - [bold]{k}[/]: {v}")
    else:
        print(artifacts) # this should never happen...

    print()

    try:
        host.write_cache()
    except:
        print()
        print(" │")
        log_warn(f"Could not write the build cache")
        print(f"[yellow]  ╰─> An exception occured while storing the build cache file.[/]")
        print(f"[yellow]      This might result in anomalous behavior in future build system invocations.[/]")
        print(f"[yellow]      You may delete the 'artifacts' directory if this is the case.[/]")
        print()
        console.print_exception()

    return artifacts
