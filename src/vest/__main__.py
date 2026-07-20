import os
import argparse
import traceback
import subprocess
from rich import print
from rich.console import Console
import rich.traceback

from vest.common.log import is_agent, log_warn, log_error_hdr, log_success_hdr
from vest.spec.host import StandaloneHost
from vest.spec.types import BuildError, UsageError

def main():
    console = Console()
    rich.traceback.install()

    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--task", help = "The task to run.", required = True)
    parser.add_argument("-p", "--path", default = "./build.vest", help = "The path to the target component.")
    parser.add_argument("-r", "--run", action = "store_true", help = "If set, the 'run_script' of the given task will be invoked.")
    parser.add_argument("--no-cache", action = "store_true", help = "If set, the results of the previous build will be ignored.")
    args, extra_args = parser.parse_known_args()

    def parse_extra_args():
        transformed: dict[str, str] = {}

        prev_arg: str | None = None
        expecting_key = True

        for arg in extra_args:
            is_key = arg.startswith("-")
            if is_key != expecting_key:
                if expecting_key:
                    # Two keys right next to each other (e.g --type --arch)
                    if prev_arg is not None:
                        log_error_hdr(f"Two or more values specified for parameter {prev_arg}.")
                        exit(1)
                    else:
                        log_error_hdr(f"Stray argument {arg} found.")
                        exit(1)
                else:
                    # Two values right next to each other (e.g. --arch amd64 release)
                    log_error_hdr(f"No value found for parameter {prev_arg}.")
                    exit(1)

            if not expecting_key:
                # There isn't really a possibility where we don't have a previous arg here. We're looking for a value, thus we went over the first iteration
                # (which was looking for a key).
                assert prev_arg is not None

                # This is value! "prev_arg" holds the key, while "arg" holds the value.
                transformed[prev_arg] = arg

            prev_arg = arg
            expecting_key = not expecting_key

        return transformed

    host = StandaloneHost(
        parameters = parse_extra_args(),
        load_cache = not args.no_cache
    )

    try:
        if os.path.isdir(args.path):
            args.path = os.path.join(args.path, "build.vest")

        component = host.eval_component(args.path)
    except Exception as ex:
        log_error_hdr("Could not evaluate the component")
        print(f"[red]  ╰─> {ex}[/]")
        print()

        console.print_exception()
        exit(1)

    if not any(t.name == args.task for t in component.tasks):
        log_error_hdr(f"No task named '{args.task}'.")
        print("[red]  ╰─> The defined tasks are:[/]")

        for task in component.tasks:
            if task.description is not None:
                print(f"[red]        - {task.name}: {task.description}[/]")
            else:
                print(f"[red]        - {task.name}[/]")

        exit(1)

    try:
        task = next(x for x in component.tasks if x.name == args.task)
        artifacts = host.run_task(task)
    except Exception as ex:
        if type(ex) is UsageError:
            # A UsageError indicates that neither Vest or the components in question are at fault - the user might've e.g. not specified a
            # required parameter. In this case, we don't print the stacktrace at all.
            print(" │")
            log_error_hdr(f"Could not build [bold]{component.name}:{args.task}[/]")
            print(f"[red]  ╰─> {ex}[/]")
            print()
            exit(1)

        # https://github.com/Textualize/rich/blob/master/rich/traceback.py#L234
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
        log_error_hdr(f"Could not build [bold]{component.name}:{args.task}[/]")
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
        exit(1)

    print(" │")
    log_success_hdr(f"Component [bold]{component.name}:{args.task}[/] built successfully")

    if not args.run:
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

    if args.run:
        if task.run_script == None:
            log_error_hdr(f"Cannot run/debug the artifacts of [bold]{component.name}:{task.name}[/]")
            print(f"[red]  ╰─> The component does not define a 'run_script' to invoke.[/]")
            exit(1)

        run_args = task.run_script(artifacts)
        assert len(run_args) > 0

        console.show_cursor()

        # Hand off control to the script, so that we don't mess stuff up with any
        # e.g. signal handlers we may have installed
        os.execvp(run_args[0], run_args)

if __name__ == "__main__":
    main()