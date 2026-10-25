"""
This file defines functions used within the component-based build system.
For more information, see `/docs/components.md`.
"""

import os
import re
import shutil
import inspect
import threading
import subprocess
from glob import glob
from typing import IO, Any, Callable, Concatenate, Generic, LiteralString, ParamSpec, TypeVar, cast, overload
from rich.text import Text

from vest.common.collections import find, single
from vest.common.log import LogLevel, log_command, log_output
from vest.spec.caching import restore_task_cache
from vest.spec.types import Component, ComponentTask, ExternalRepoResolver, InvocationError, OutputFormatter, TTaskReturn, UsageError
from vest.spec.host import host

TLiteral = TypeVar("TLiteral", bound = str)
TParams = ParamSpec("TParams")

def component(
    *,
    name: str,
    source: ExternalRepoResolver | None = None,
    sources: list[str] = ["./**/*"],
    cached: bool = False
):
    """
    Declares a component. This function should always be called from component manifests,
    as soon as possible (usually after all imports).

    @name: The unique name of the component.
    @source: The resolver to use for external repositories. If `None`, the component is not external.
    @sources: Defines the source files (via glob patterns) that compose this project. If not defined, this will be equivalent to all files in the directory of the component's manifest.
    @cached: If `True`, when the `@sources`, artifacts, and build parameters haven't changed from the previous build, component tasks will not be ran, and the previously created artifacts will be returned instead.
    """

    path = host().current_component_path
    if path is None:
        raise Exception("Cannot declare a component outside a component manifest.")

    if host().current_component is not None:
        raise Exception("A component already has been declared in this file context.")
    
    created = Component(
        name = name,
        source = source,
        sources = sources,
        path = path,
        cached = cached,
        base_dir = os.path.dirname(path)
    )

    host().current_component = created

    if source is not None:
        # If there is no external repository resolver, then the base is equal
        # to the directory where the component file is located
        created.base_dir = source.get_directory()

def task(description: str | None = None):
    """
    Declares a task. Functions marked with this decorator should return the paths to the
    artifacts produced by running this task, in the form of either:
        - a `list[str]`, when the artifacts are not of importance to dependent tasks,
        - a `dict[str | list[str]]`, to give names to the artifacts,
        - a `str`, when only one artifact is produced,
        - `None`, if no artifact is produced.

    The paths are relative to the base directory. The current working directory is guaranteed
    to be set to the base directory when the task is running.

    @description: Provides a user-friendly description of the task. Displayed when querying available tasks from the CLI.
    """

    cmpn = require_component("Tasks can only be declared after a component declaration.")

    def decorator(fn: Callable[[], TTaskReturn]) -> ComponentTask[TTaskReturn]:
        task = ComponentTask(
            name = fn.__name__,
            description = description,
            body = fn,
            origin = cmpn,
        )

        if task.origin.cached:
            # Before registering the task, see if there is a cache entry for this task that
            # is valid. If it is, we will mark this task as complete from the get-go and
            # use the artifacts from the previous build.
            restore_task_cache(task)

        cmpn.tasks.append(task)
        return task

    return decorator

def dependency(path: str, task: str) -> Any:
    """
    Defines a dependency on a task of another component, passing along its return value.

    @path: The path to the component, relative to the repository's root.
    @task: The name of the target task.
    """
    current_task = require_task()
    
    abs_path = os.path.join(host().repo_dir, path)
    if os.path.isdir(abs_path):
        abs_path = os.path.join(abs_path, "build.vest")

        if not os.path.isfile(abs_path):
            raise Exception(f"The component path '{path}' points to a directory which does not have a 'build.vest' file.")
    elif not os.path.exists(abs_path):
        raise Exception(f"The component '{path}' does not exist.")

    dep = host().eval_component(abs_path)

    task_obj = find(dep.tasks, lambda x: x.name == task)
    if task_obj is None:
        raise Exception(f"The '{dep.name}' component does not declare a '{task}' task.")
    
    artifacts = host().check_task(task_obj)

    if task_obj not in current_task.known_dependencies:
        current_task.known_dependencies.append(task_obj)

    return artifacts

def self_dependency(task: ComponentTask[TTaskReturn]) -> TTaskReturn:
    "Defines a dependency on a task of the calling component."
    return host().check_task(task)

def dependent_on(path: str, task: str):
    """
    Marks that a function call is dependent on a component task being ran at least once.
    The output of the task will be stored as the first argument.
    """
    def decorator(fn: Callable[Concatenate[Any, TParams], TTaskReturn]) -> Callable[TParams, TTaskReturn]:
        def wrapper(*args: TParams.args, **kwargs: TParams.kwargs):
            artifacts = dependency(path, task)
            return fn(artifacts, *args, **kwargs)
        
        return wrapper

    return decorator

def artifact_root_path_of(component: Component):
    """
    Returns the artifact root path of the given component. This path might point
    to a non-existent directory if the target component has not invoked the
    `artifact_root` or `artifact_dir` function.
    """
    return os.path.join(host().repo_dir, "artifacts", component.name).rstrip("/")

def artifact_dir_path_of(component: Component, task: ComponentTask):
    """
    Returns the artifact path of the given component task. This path might point
    to a non-existent directory if the target component has not invoked the
    `artifact_dir` function.
    """
    return os.path.join(artifact_root_path_of(component), task.name).rstrip("/")

def artifact_dir():
    """
    Retrieves the absolute path to the artifact directory of the currently running
    component task, creating it if it doesn't exist.

    The returned path will never have a trailing slash.
    """
    path = artifact_dir_path_of(
        require_component(),
        require_task("'artifact_dir' only applies to tasks. Did you mean to call 'artifact_root'?")
    )

    os.makedirs(path, exist_ok = True)
    return path

def artifact_root():
    """
    Retrieves the absolute path to the artifact directory of the currently running
    component, which contains both tasks and artifacts common to the entire component
    (e.g. the contents of a cloned remote repository).

    The returned path will never have a trailing slash.
    """
    path = artifact_root_path_of(require_component())
    os.makedirs(path, exist_ok = True)
    return path

def clean_artifact_dir():
    "Removes all files and folders from the component task's artifact directory."

    path = artifact_dir_path_of(
        require_component(),
        require_task("'clean_artifact_dir' only applies to tasks. Did you mean to call 'clean_artifact_root'?")
    )

    if not os.path.isdir(path):
        return

    shutil.rmtree(path)
    os.makedirs(path)

def clean_artifact_root():
    "Removes all files and folders from the component's artifact root. This includes all artifact directories of the component's tasks."

    path = artifact_root_path_of(require_component())
    if not os.path.isdir(path):
        return

    shutil.rmtree(path)
    os.makedirs(path)

def run(filename: str, args: list[str] = [], is_tool = False, stderr_is_stdout = False, formatter: OutputFormatter | None = None):
    """
    Runs an executable.

    @filename: The name of the file to execute.
    @args: The arguments to pass into the process.
    @is_tool: If `True`, the function will add a `--log-plain` argument, and translate prefixes (e.g. `info: `) to appropriate log types.
    @stderr_is_stdout: If `True`, standard error output will be considered to be regular output.
    @formatter: Changes how the output of the process is displayed. See `OutputFormatter`.
    """

    if is_tool:
        args.append("--log-plain")

    filename = filename.strip()
    log_command(filename, args, host().repo_dir, formatter)

    proc = subprocess.Popen(
        [filename, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    lock = threading.Lock()
    errors: list[str] = []

    def output(line: str, level: LogLevel):
        with lock:
            log_output(line, level)

    def forward(line: str, fallback: LogLevel):
        line_raw = Text.from_ansi(line).plain

        if re.search(r": *warn(?:ing)?.*:", line_raw, re.IGNORECASE):
            output(line, "warn")
        elif re.search(r": *error.*:", line_raw, re.IGNORECASE):
            errors.append(line_raw)
            output(line, "error")
        else:
            output(line, fallback)

    def forward_stdout(line: str):
        if is_tool:
            line_raw = Text.from_ansi(line).plain

            if line_raw.startswith("warn"):
                output(line_raw, "warn")
            elif line_raw.startswith("error"):
                errors.append(line_raw)
                output(line_raw, "error")
            elif line_raw.startswith("info"):
                output(line_raw[5:], "info")

            return

        forward(line, "info")

    def forward_stderr(line: str):
        if is_tool and Text.from_ansi(line).plain.startswith("error"):
            errors.append(line[5:])
            output(line[5:], "error")
        else:
            forward(line, "error")

    def stream_reader(stream: IO[str], callback: Callable[[str], None]):
        while True:
            line = stream.readline()
            if not line:
                break

            callback(line.replace("\r", "").replace("\n", ""))

    stdout_thread = threading.Thread(target=stream_reader, args=(proc.stdout, forward_stdout))
    stderr_thread = threading.Thread(target=stream_reader, args=(proc.stderr, forward_stderr if not stderr_is_stdout else forward_stdout))

    stdout_thread.start()
    stderr_thread.start()

    proc.wait()

    stdout_thread.join()
    stderr_thread.join()

    if proc.returncode != 0:
        raise InvocationError(filename, args, proc.returncode, errors[0] if errors else None)

def run_tool(filename: str, args: list[str] = []):
    "Equivalent to `run(filename, args, is_tool = True)`."
    run(filename, args, is_tool = True)

def require_task(reason: str | None = None) -> ComponentTask:
    "Specifies that the function requires a task to be currently executing."
    task = host().current_task
    if task is None:
        raise Exception(reason if reason is not None else f"The '{inspect.stack()[1].function}' function can only be called from component tasks.")

    return task

def require_component(reason: str | None = None) -> Component:
    "Specifies that the function requires a component."
    component = host().current_component
    if component is None:
        raise Exception(reason if reason is not None else f"The '{inspect.stack()[1].function}' function can only be called from components.")

    return component

_T1 = TypeVar("_T1", bound = LiteralString)
_T2 = TypeVar("_T2", bound = LiteralString)
_T3 = TypeVar("_T3", bound = LiteralString)
_T4 = TypeVar("_T4", bound = LiteralString)
_T5 = TypeVar("_T5", bound = LiteralString)
_T6 = TypeVar("_T6", bound = LiteralString)

class UnreadBuildParameter(Generic[TLiteral]):
    name: str

    def __init__(self, value: str | None, name: str) -> None:
        super().__init__()
        self._value = value
        self.name = name

    @property
    def value(self) -> TLiteral:
        if self._value is None:
            raise UsageError(f"Missing build parameter: {self.name}")

        return cast(TLiteral, self._value)

    # This is a bit of a hack - but is the only way for type checkers to properly detect that we want
    # an array of specific literals, and NOT widen the result to a `str`.

    @overload
    def constrain(self, __v1: _T1) -> "UnreadBuildParameter[_T1]": ...
    
    @overload
    def constrain(self, __v1: _T1, __v2: _T2) -> "UnreadBuildParameter[_T1 | _T2]": ...
    
    @overload
    def constrain(self, __v1: _T1, __v2: _T2, __v3: _T3) -> "UnreadBuildParameter[_T1 | _T2 | _T3]": ...
    
    @overload
    def constrain(self, __v1: _T1, __v2: _T2, __v3: _T3, __v4: _T4) -> "UnreadBuildParameter[_T1 | _T2 | _T3 | _T4]": ...
    
    @overload
    def constrain(self, __v1: _T1, __v2: _T2, __v3: _T3, __v4: _T4, __v5: _T5) -> "UnreadBuildParameter[_T1 | _T2 | _T3 | _T4 | _T5]": ...
    
    @overload
    def constrain(self, __v1: _T1, __v2: _T2, __v3: _T3, __v4: _T4, __v5: _T5, __v6: _T6) -> "UnreadBuildParameter[_T1 | _T2 | _T3 | _T4 | _T5 | _T6]": ...
    
    def constrain(self, *values: str) -> "UnreadBuildParameter[Any]":
        """
        Constrains the set of valid values for the parameter. For example:
        
            # ARCH will be of type `Literal["amd64"] | Literal["aarch64"]`. If the user
            # provides a value outside this set, a usage error will be reported.
            ARCH = parameter("-a", "--arch").constrain("amd64", "aarch64").value
        """
        if self._value not in values:
            quoted = [f'"{x}"' for x in values]
            choices = quoted[0] if len(quoted) <= 1 else ', '.join(quoted[:-1]) + (', or ' if len(quoted) > 2 else ' or ') + quoted[-1]

            if self._value is None:
                raise UsageError(f"Missing build parameter: {self.name}, which must be either {choices}")

            raise UsageError(f"{self.name} must be either {choices}")

        return cast("UnreadBuildParameter[Any]", self)

def parameter(*args: str):
    """
    Accepts a string parameter given by the build host. This is often an argument given by the user. For example:

    ```
    # When the user builds with "-a amd64 --type release"...
    ARCH = parameter("-a", "--arch").value # ...this will be "amd64"...
    TYPE = parameter("-c", "--type").value # ...and this will be "release".
    ```

    This requires the parameter to be provided. For optional parameters, see `optional_parameter`.
    """
    value = next((host().parameters[key] for key in args if key in host().parameters), None)
    return UnreadBuildParameter(value, "/".join(args))

