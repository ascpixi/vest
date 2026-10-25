import os
import time
import subprocess
import traceback

import rich
from rich.console import Console
from rich.markup import escape
from rich.text import Text
import rich.traceback

from vest.common.log import (
    format_duration,
    is_agent,
    log_error_hdr,
    log_print,
    log_stats,
    log_success_hdr,
    log_task_chain,
    log_task_failed,
    log_warn
)
from vest.spec.host import StandaloneHost
from vest.spec.types import BuildError, InvocationError, UsageError

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

    started = time.monotonic()
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
        log_print(f"[red]  ╰─> {ex}[/]")
        log_print()

        if not isinstance(ex, (UsageError, BuildError)):
            console.print_exception()

        raise VestFailure()

    if not any(t.name == task for t in component.tasks):
        log_error_hdr(f"No task named '{task}'.")
        log_print("[red]  ╰─> The defined tasks are:[/]")

        for defined_task in component.tasks:
            if defined_task.description is not None:
                log_print(f"[red]        - {defined_task.name}: {defined_task.description}[/]")
            else:
                log_print(f"[red]        - {defined_task.name}[/]")

        raise VestFailure()

    try:
        found_task = next(x for x in component.tasks if x.name == task)
        artifacts = host.run_task(found_task)
    except Exception as ex:
        log_task_failed()

        if type(ex) is UsageError:
            # A UsageError indicates that neither Vest or the components in question are at fault - the user might've e.g. not specified a
            # required parameter. In this case, we don't print the stacktrace at all.
            log_error_hdr(f"Could not build [bold]{component.name}:{task}[/]")
            log_print(f"[red]  ╰─> {ex}[/]")
            log_print()
            raise VestFailure()

        if type(ex) is subprocess.CalledProcessError:
            stdout = ex.stdout.decode("utf-8") if type(ex.stdout) is bytes else str(ex.stdout)
            stderr = ex.stderr.decode("utf-8") if type(ex.stderr) is bytes else str(ex.stderr)

            stdout = stdout.strip()
            stderr = stderr.strip()
    
            if stdout:
                log_print(f"[red]Standard output:[/]")
                log_print(escape(stdout))
                log_print()

            if stderr:
                log_print(f"[red]Standard error:[/]")
                log_print(escape(stderr))
                log_print()

        # A BuildError indicates that the cause of the error is incorrect usage of the
        # component system (as opposed to e.g. a bug). In this case, we don't need to
        # show the frames that belong to the component system.
        if not isinstance(ex, BuildError):
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

            log_print()
            if not is_agent():
                console.print_exception()
            else:
                traceback.print_exc()

        log_error_hdr(f"Could not build [bold]{component.name}:{task}[/] [dim]· {format_duration(time.monotonic() - started)}[/]")

        for (i, (key, value)) in enumerate(failure_details(ex, host.repo_dir)):
            log_print(f"[red]{'  ╰─> ' if i == 0 else '      '}[bold]{key:<8}[/][/]  {escape(value)}")

        log_print()
        raise VestFailure()

    log_success_hdr(f"[bold green]built {component.name}:{task}[/] in {format_duration(time.monotonic() - started)} [dim]· {log_stats()}[/]")

    if type(artifacts) is str:
        log_print(f"  ╰─> You may find the resulting artifact in [bold]{artifacts}[/].")
    elif type(artifacts) is list:
        log_print(f"  ╰─> The following artifacts have been created:")

        for entry in artifacts:
            log_print(f"        - {entry}")
    elif type(artifacts) is dict:
        log_print(f"  ╰─> The following named artifacts have been created:")

        for (k, v) in artifacts.items():
            log_print(f"        - [bold]{k}[/]: {v}")
    else:
        log_print(str(artifacts)) # this should never happen...

    log_print()

    try:
        host.write_cache()
    except:
        log_warn(f"Could not write the build cache")
        log_print(f"[yellow]  ╰─> An exception occured while storing the build cache file.[/]")
        log_print(f"[yellow]      This might result in anomalous behavior in future build system invocations.[/]")
        log_print(f"[yellow]      You may delete the 'artifacts' directory if this is the case.[/]")
        log_print()
        console.print_exception()

    return artifacts

def failure_details(ex: Exception, repo_dir: str):
    "Lists the facts about a failed build that are restated at the very end of its log."

    def shorten(s: str):
        return s.replace(repo_dir, ".")

    details = [("task", " › ".join(log_task_chain()))]

    if isinstance(ex, InvocationError):
        details += [("command", shorten(" ".join(ex.command))), ("exit", str(ex.code))]

    if isinstance(ex, InvocationError) and ex.first_error:
        details.append(("error", shorten(Text.from_ansi(ex.first_error).plain.strip())))
    elif isinstance(ex, BuildError):
        details.append(("error", str(ex)))
    else:
        details.append(("error", f"{type(ex).__name__}: {ex}"))

    frames = [
        f"{os.path.relpath(frame.filename, repo_dir)}:{frame.lineno} in {frame.name}"
        for frame in reversed(traceback.extract_tb(ex.__traceback__))
        if frame.filename.endswith(".vest")
    ]

    details += [("at" if i == 0 else "", frame) for (i, frame) in enumerate(frames)]
    return details
