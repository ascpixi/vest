import os
import time
import atexit
import rich
from dataclasses import dataclass, field
from typing import Literal
from rich.console import Console
from rich.text import Text

from vest.spec.types import OutputFormatter

LogLevel = Literal["info", "warn", "error"]

PALETTE = ["#7dcfff", "#bb9af7", "#9ece6a", "#e0af68", "#73daca", "#ff9e64", "#ff79c6", "#82aaff"]
LEVEL_STYLES: dict[LogLevel, str] = { "info": "dim", "warn": "yellow", "error": "red" }
MUTED_STYLE = "#6c7086"

REGION = "  "
OUTPUT = "    "
INDENT = "    "

@dataclass
class _LogStats:
    tasks: int = 0
    cached: int = 0
    warnings: int = 0

@dataclass
class _LogState:
    tasks: list[tuple[str, float]] = field(default_factory = list)
    "The names of the tasks that are currently running, alongside their start times. The innermost task is last."

    region: str | None = None
    "The task whose lines were printed most recently."

    colors: dict[str, str] = field(default_factory = dict)
    blank: bool = True
    after_header: bool = False

    repo_dir: str | None = None
    formatter: OutputFormatter | None = None
    command_wrapped: bool = False
    output_open: bool = False
    after_block: bool = False

_stats = _LogStats()
_state = _LogState()
_console = Console(soft_wrap = True, highlight = False)

def is_github_actions():
    return "GITHUB_RUN_ID" in os.environ

def is_agent():
    return "CLAUDECODE" in os.environ or "GEMINI_CLI" in os.environ or "CURSOR_AGENT" in os.environ

def is_non_interactive():
    return is_github_actions() or is_agent()

def log_reset_terminal():
    rich.reconfigure()
    rich.console.Console().show_cursor()

def log_deinit():
    """Performs on-exit de-initialization of the logging sub-system."""
    if not is_non_interactive():
        log_reset_terminal()

def format_duration(seconds: float):
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.2f}s"

def log_stats():
    "Summarizes the tasks and warnings logged so far, e.g. `3 tasks, 1 cached, 2 warnings`."
    return f"{_plural(_stats.tasks, 'task')}, {_stats.cached} cached, {_plural(_stats.warnings, 'warning')}"

def log_task_started(name: str):
    parent = _current_task()
    _header(
        name,
        _label(name, chip = True), "  ",
        ("building", f"bold {_color(name)}"),
        (f" for {parent}", "dim") if parent else None
    )

    _state.tasks.append((name, time.monotonic()))
    _stats.tasks += 1

def log_task_cached(name: str):
    _line(_text(_label(name), ("  cached", "green"), ("  up to date", "dim")))
    _stats.tasks += 1
    _stats.cached += 1

def log_task_finished():
    name, started = _state.tasks.pop()
    _closing_line(name, ("✓ done", "bold green"), (f" in {format_duration(time.monotonic() - started)}", "dim"))

def log_task_failed():
    "Marks the innermost running task as failed. The task stays in the chain returned by `log_task_chain`."
    if not _state.tasks:
        return

    name, started = _state.tasks[-1]
    _closing_line(name, ("failed", "bold red"), (f" after {format_duration(time.monotonic() - started)}", "dim"))

def log_task_chain():
    "Returns the names of the tasks that are currently running, starting with the outermost one."
    return [name for (name, _) in _state.tasks]

def log_command(filename: str, args: list[str], repo_dir: str, formatter: OutputFormatter | None = None):
    """
    Logs the invocation of an external process. Occurrences of `repo_dir` in the command and its output are
    shortened to `.`, and its output is passed through `formatter`, if specified.
    """
    _state.repo_dir = repo_dir
    _state.formatter = formatter
    _state.command_wrapped = False
    _state.after_block = False
    _enter(_current_task())

    groups = _command_groups(_shorten(filename), [_shorten(x) for x in args])
    if not _wraps():
        _print(REGION, Text(" ").join(groups))
        return

    prefix, line = REGION, Text()
    for group in groups:
        if line.plain and len(prefix) + len(line.plain) + 1 + len(group.plain) > _console.width:
            _print(prefix, line)
            _state.command_wrapped = True
            prefix, line = REGION + INDENT, Text()

        line = Text(" ").join([line, group]) if line.plain else group

    _emit(prefix, line)

def log_output(line: str, level: LogLevel = "info"):
    "Logs a line of output of the most recently invoked process."
    if _state.command_wrapped and not _state.output_open:
        _gap()
        _state.output_open = True

    if not line.strip():
        _gap()
        return

    block = _state.formatter(line) if _state.formatter else None
    if block == []:
        return

    if level == "warn":
        _stats.warnings += 1

    text = Text.from_ansi(_shorten(line).rstrip())
    if _annotate(level, text):
        return

    if block and _wraps():
        _gap()
        for x in block:
            _line(x, prefix = OUTPUT, output = True)

        _state.after_block = True
        return

    if _state.after_block:
        _gap()
        _state.after_block = False

    text.stylize_before(LEVEL_STYLES[level])
    _line(text, prefix = OUTPUT, output = True)

def log_info(msg: str | Text):
    """Logs an informational message to the console."""
    _line(_markup(msg))

def log_warn(msg: str | Text):
    """Logs a warning message to the console."""
    _stats.warnings += 1
    if not _annotate("warn", _markup(msg)):
        _line(_text(("warning: ", "bold yellow"), _markup(msg, "yellow")))

def log_error(msg: str | Text):
    """Logs an error message to the console."""
    if not _annotate("error", _markup(msg)):
        _line(_text(("error: ", "bold red"), _markup(msg, "red")))

def log_error_hdr(msg: str):
    "Prints an error header to the console."
    _gap()
    _print((" vest ", "bold #1a1b26 on #f7768e"), " ", ("error: ", "bold red"), Text.from_markup(msg))

def log_success_hdr(msg: str):
    "Prints a success header to the console."
    _gap()
    _print((" vest ", "bold #1a1b26 on #9ece6a"), " ", Text.from_markup(msg))

def log_print(msg: str = ""):
    "Prints a line of Rich markup as-is, outside of any task's region."
    _print(Text.from_markup(msg))

def _plural(count: int, noun: str):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"

def _text(*parts: str | Text | tuple[str, str] | None):
    return Text.assemble(*(x for x in parts if x))

def _markup(msg: str | Text, style: str = ""):
    if isinstance(msg, str):
        return Text.from_markup(msg, style = style)

    text = msg.copy()
    text.stylize_before(style)
    return text

def _shorten(s: str):
    return s.replace(_state.repo_dir, ".") if _state.repo_dir else s

def _wraps():
    "Lines are only wrapped by Vest itself in interactive terminals - otherwise, every line is printed whole."
    return _console.is_terminal and not is_non_interactive()

def _current_task():
    return _state.tasks[-1][0] if _state.tasks else None

def _color(task: str):
    component = task.split(":")[0]
    return _state.colors.setdefault(component, PALETTE[len(_state.colors) % len(PALETTE)])

def _label(task: str, chip = False):
    return (task, f"bold #1a1b26 on {_color(task)}" if chip else f"bold {_color(task)}")

def _print(*parts: str | Text | tuple[str, str] | None):
    line = _text(*parts)
    _console.print(line)
    _state.blank = not line.plain.strip()
    _state.after_header = False

def _gap():
    if not _state.blank:
        _print()

def _emit(prefix: str, line: Text):
    "Prints `prefix` followed by `line`. When wrapped, the continuation lines are indented further than `prefix`."
    line = Text(prefix) + line
    if not _wraps():
        _print(line)
        return

    first = line.wrap(_console, _console.width, overflow = "fold")[0]
    _print(first)

    rest = line[len(first.plain):]
    rest = rest[len(rest.plain) - len(rest.plain.lstrip()):]
    if rest.plain:
        for part in rest.wrap(_console, _console.width - len(prefix + INDENT), overflow = "fold"):
            _print(prefix + INDENT, part)

def _header(task: str, *parts: str | tuple[str, str] | None):
    "Starts the region of a task. Headers that directly follow each other aren't separated by blank lines."
    if not _state.after_header:
        _gap()

    _emit("", _text(*parts))
    _state.region = task
    _state.after_header = True
    _state.output_open = False

def _enter(task: str | None, output = False):
    """
    Prepares for a line in the region of `task`, re-opening the region if another task has printed since. Unless
    `output` is `True`, an open block of process output is closed first.
    """
    if _state.output_open and not output:
        _gap()
        _state.output_open = False

    if task is not None and _state.region != task:
        _header(task, _label(task), ("  continued", "dim"))

def _line(text: Text, task: str | None = None, prefix = REGION, output = False):
    "Prints a line in the region of `task` - or, if not specified, the task that is currently running."
    task = task or _current_task()
    _enter(task, output)
    _emit(prefix if task else "", text)

def _closing_line(task: str, *parts: str | tuple[str, str]):
    if _state.region == task and not _state.after_header:
        _gap()

    _line(_text(*parts), task)

def _annotate(level: LogLevel, text: Text):
    "Prints warnings and errors as GitHub Actions annotations when running in a workflow."
    if not is_github_actions() or level == "info":
        return False

    _print(f"::{'warning' if level == 'warn' else 'error'}::", text)
    return True

def _command_groups(filename: str, args: list[str]):
    "Splits a command into the units it may be wrapped between. A flag is kept together with the value that follows it."
    groups = [_text(("$ ", MUTED_STYLE), (filename, "bold #f9e2af"))]

    i = 0
    while i < len(args):
        if args[i].startswith("-") and i + 1 < len(args) and not args[i + 1].startswith("-"):
            groups.append(_text((args[i], MUTED_STYLE), " ", args[i + 1]))
            i += 2
        else:
            groups.append(Text(args[i], MUTED_STYLE if args[i].startswith("-") else ""))
            i += 1

    return groups

atexit.register(log_deinit)
