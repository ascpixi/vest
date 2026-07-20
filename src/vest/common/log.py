import os
import atexit
import shutil
import rich
from rich import print
from rich.console import Console
from rich.text import Text
from rich.table import Table

_current_log_indent = 0
_task_stack: list[str] = []

def is_github_actions():
    return "GITHUB_RUN_ID" in os.environ

def is_agent():
    return "CLAUDECODE" in os.environ or "GEMINI_CLI" in os.environ or "CURSOR_AGENT" in os.environ

def is_non_interactive():
    return is_github_actions() or is_agent()

def log_dedent(delta: int = 2):
    global _current_log_indent
    _current_log_indent -= delta
    _task_stack.pop()

def log_reset_terminal():
    rich.reconfigure()
    rich.console.Console().show_cursor()

def log_deinit():
    """Performs on-exit de-initialization of the logging sub-system."""
    if not is_non_interactive():
        log_reset_terminal()

def log_get_effective_width():
    return shutil.get_terminal_size().columns - _current_log_indent

def log_dependency(full_name: str, fulfilled = False):
    global _current_log_indent

    if not fulfilled:
        _current_log_indent += 2
        _task_stack.append(full_name)

    if is_agent():
        print(f"{full_name} was built before - skipping because of cache." if fulfilled else f"Building {full_name}...")
        return

    formatted = (
        f"◆ Dependency on [bold]{full_name}[/] [bright_black](fullfilled previously)[/]" if fulfilled else
        f"◇ Building [bold]{full_name}[/]..."
    )

    if _current_log_indent == 0:
        print(f"[white] {formatted}[/]")
    else:
        print(f"[white] {'├'.ljust(_current_log_indent, '─')} {formatted}[/]")

def log(prefix: str, msg: str | Text):
    """
    Logs a message to the console. All arguments can be formatted using Rich markup.
    If executing in a CI environment, no special formatting will be applied.
    """

    if not isinstance(msg, Text):
        msg = Text.from_markup(msg)

    if is_non_interactive():
        print(prefix, msg)
        return

    def create_table(border: Text):
        grid = Table.grid()
        grid.add_column()
        grid.add_column()
        grid.add_column()
        grid.add_column()

        grid.add_row(
            border,
            Text.from_markup(prefix),
            "  ",
            msg
        )

        return grid

    console = Console()
    with console.capture() as capture:
        console.print(create_table(Text(" │".ljust(_current_log_indent))))
    
    simulated = capture.get()
    print(create_table(
        Text((
            # Make sure the first row, which holds the border, is as large as the table.
            (" │".ljust(_current_log_indent + 2) + "\n") * simulated.count("\n")
        ).rstrip("\n"))
    ))

def _get_agent_label(label: str):
    if len(_task_stack) == 0:
        return f"({label}) "
    
    return f"({label}@{_task_stack[-1]}) "

def log_info(msg: str | Text):
    """Logs an informational message to the console."""
    log("[white bold]info[/]" if not is_non_interactive() else "(info)  " if is_github_actions() else _get_agent_label("info"), msg)

def log_warn(msg: str | Text):
    """Logs a warning message to the console."""
    if isinstance(msg, Text):
        msg.stylize("#ffffaf")
    else:
        msg = f"[#ffffaf]{msg}[/]"

    log("[yellow bold]warn[/]" if not is_non_interactive() else "::warning::" if is_github_actions() else _get_agent_label("warning"), msg)

def log_error(msg: str | Text):
    """Logs an error message to the console."""
    if isinstance(msg, Text):
        msg.stylize("#ffcbd7")
    else:
        msg = f"[#ffcbd7]{msg}[/]"

    log("[red bold]error[/]" if not is_non_interactive() else "::error::" if is_github_actions() else _get_agent_label("error"), msg)

def log_error_hdr(msg: str):
    "Prints an error header to the console."
    if is_agent():
        print(f"Failure: {msg}")
        return

    print(f"[black on red] × ERROR [/] [red]{msg}[/]")

def log_success_hdr(msg: str):
    "Prints a success header to the console."
    if is_agent():
        print(f"Success: {msg}")
        return

    print(f"[black on green] ❯ SUCCESS [/] [green]{msg}[/]")

atexit.register(log_deinit)
