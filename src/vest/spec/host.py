import os
import re
import sys
import json
import time
import types
from datetime import date
from typing import Any, TypedDict

from vest.common.log import log_dedent, log_dependency, log_error_hdr
from vest.spec.types import Component, ComponentTask, TTaskReturn

global_component_host: "StandaloneHost | None" = None

# Maps sanitized root package names -> absolute repo_dir paths, so we can detect
# collisions when two projects share the same directory basename.
_root_pkg_registry: dict[str, str] = {}

def _safe_name(s: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    if name and name[0].isdigit():
        name = "_" + name
    return name

def _script_package(script_dir: str, repo_dir: str) -> str:
    """
    Ensures sys.modules contains synthetic packages for every directory level from
    repo_dir down to script_dir, then returns the __package__ name for that directory.
    Relative imports in .vest scripts resolve against this hierarchy.
    """
    abs_repo = os.path.abspath(repo_dir)
    base = _safe_name(os.path.basename(abs_repo))

    # Resolve collisions: if another repo already claimed this name, append a counter.
    candidate = base
    suffix = 2
    while candidate in _root_pkg_registry and _root_pkg_registry[candidate] != abs_repo:
        candidate = f"{base}_{suffix}"
        suffix += 1
    root_name = candidate

    if root_name not in sys.modules:
        _root_pkg_registry[root_name] = abs_repo
        m = types.ModuleType(root_name)
        m.__path__ = [repo_dir]   # type: ignore[attr-defined]
        m.__package__ = root_name
        sys.modules[root_name] = m

    try:
        rel = os.path.relpath(script_dir, repo_dir)
    except ValueError:
        # Different drives on Windows — fall back to a flat package for this directory.
        flat = _safe_name(os.path.basename(script_dir))
        if flat not in sys.modules:
            m = types.ModuleType(flat)
            m.__path__ = [script_dir]   # type: ignore[attr-defined]
            m.__package__ = flat
            sys.modules[flat] = m
        return flat

    if rel == ".":
        return root_name

    current_pkg = root_name
    current_dir = repo_dir
    for part in rel.replace("\\", "/").split("/"):
        current_dir = os.path.join(current_dir, part)
        child = f"{current_pkg}.{_safe_name(part)}"
        if child not in sys.modules:
            m = types.ModuleType(child)
            m.__path__ = [current_dir]   # type: ignore[attr-defined]
            m.__package__ = child
            sys.modules[child] = m
        current_pkg = child

    return current_pkg

class TaskDescriptor(TypedDict):
    component_path: str
    task: str

class BuildCacheEntry(TypedDict):
    component_name: str
    task_name: str
    time: float
    artifacts: Any
    dependencies: list[TaskDescriptor]
    foreign_files: list[str]

class BuildCache(TypedDict):
    parameters: dict[str, str]
    entries: list[BuildCacheEntry]

class StandaloneHost:
    "Represents a host deploying a root component."

    def __init__(self, parameters: dict[str, str] = {}, load_cache = True) -> None:
        """
        @parameters: The build parameters to make accessible to all components.
        """

        self._loaded_components: dict[str, Component] = {} # abs paths <-> component objects

        self.parameters = parameters
        "The string parameters that were provided to the host."

        self.repo_dir = os.getcwd()
        "The base directory of the component."

        self.current_component_path: str | None = None
        "The path of the component that is currently being processed."

        self.current_component: Component | None = None 
        "The component that is currently being processed. If accessed from a component, this provides metadata about itself."

        self.current_task: ComponentTask | None = None
        "The task that is currently being executed. If accessed from a task, this provides metadata about itself."

        self.now = date.today()
        "The timestamp at which the build was started."

        self.cache: BuildCache | None = None
        "The cached results of previously ran tasks."

        # Register the component host as a global, so that components can access it.
        global global_component_host
        global_component_host = self

        if load_cache and os.path.isfile("artifacts/buildcache.json"):
            try:
                cache = json.load(open("artifacts/buildcache.json"))
                parameters = cache["parameters"]

                if (
                    type(parameters) is dict and
                    all(self.parameters.get(k) == v for (k, v) in parameters.items())
                ):
                    self.cache = cache
            except:
                print()
                log_error_hdr("Could not load the global build cache for this repository")
                print("The 'artifacts/buildcache.json' file might be corrupted. It is generally recommended")
                print("to remove the entire 'artifacts' directory.")
                print()
                raise

    def eval_component(self, path: str) -> Component:
        """
        Evaluates the component defined by the manifest defined in the given path.
        If the component was already evaluated before, the cached value is returned instead.
        """

        prev_component = self.current_component
        prev_task = self.current_task

        apath = os.path.abspath(path)
        if apath in self._loaded_components:
            cmpn = self._loaded_components[apath]
            return cmpn
        
        self.current_component = None
        self.current_task = None
        self.current_component_path = apath

        script_dir = os.path.dirname(apath)
        pkg_name = _script_package(script_dir, self.repo_dir)

        glbls = globals().copy()
        glbls["__file__"] = apath
        glbls["__package__"] = pkg_name

        code = compile(open(apath).read(), apath, "exec")
        exec(code, glbls)

        if self.current_component is None:
            raise Exception(f"The file '{path}' doesn't define a component.")
        
        cmpn = self.current_component

        self.current_component = prev_component
        self.current_task = prev_task

        self._loaded_components[apath] = cmpn

        return cmpn

    def check_task(self, task: ComponentTask[TTaskReturn]) -> TTaskReturn:
        "Runs a task if it is not marked as up-to-date."

        if task.up_to_date:
            log_dependency(f"{task.origin.name}:{task.name}", True)
            return task.artifacts # type: ignore
        
        return self.run_task(task)

    def run_task(self, task: ComponentTask[TTaskReturn]) -> TTaskReturn:
        "Runs a task, regardless of its status."

        prev_component = self.current_component
        prev_task = self.current_task

        self.current_task = task
        self.current_component = task.origin

        external_src = self.current_component.source
        if external_src is not None:
            # The component is external; before running any kind of task, we need
            # to ensure the local contents exist and are synchronized with the external source.
            if external_src.check():
                external_src.retrieve()

        prev_cwd = os.getcwd()
        os.chdir(task.origin.base_dir)

        log_dependency(f"{task.origin.name}:{task.name}")
        artifacts = task.body() # Component-defined code
        log_dedent()

        # Make all relative artifact paths to absolute paths, and verify they exist 
        if isinstance(artifacts, str):
            if not os.path.isabs(artifacts):
                artifacts = os.path.join(task.origin.base_dir, artifacts)

            if not os.path.exists(artifacts):
                raise Exception(f"The returned artifact '{artifacts}' does not exist.")
        elif isinstance(artifacts, dict):
            abs_artifacts = {}
            for (k, v) in artifacts.items():
                if isinstance(v, list):
                    abs_artifacts[k] = [
                        os.path.join(task.origin.base_dir, x) if not os.path.isabs(x) else x
                        for x in v
                    ]

                    for entry in abs_artifacts[k]:
                        if not os.path.exists(entry):
                            raise Exception(f"The artifact '{k}' with entry '{entry}' does not exist.")
                else:
                    if not os.path.isabs(v):
                        abs_artifacts[k] = os.path.join(task.origin.base_dir, v)
                    else:
                        abs_artifacts[k] = v

                    if not os.path.exists(abs_artifacts[k]):
                        raise Exception(f"The artifact '{k}' with entry '{abs_artifacts[k]}' does not exist.")

            artifacts = abs_artifacts
        elif isinstance(artifacts, list):
            artifacts = [
                os.path.join(task.origin.base_dir, x) if not os.path.isabs(x) else x
                for x in artifacts
            ]

            for v in artifacts:
                if not os.path.exists(v):
                    raise Exception(f"The artifact '{v}' does not exist.")
        elif artifacts is not None:
            raise Exception(f"Unknown type returned as artifact data: {type(artifacts).__name__}")

        # This isn't very safe! Unfortunately, the type checker is unable to see that when
        # 'artifacts' (of type TTaskReturn) is of a certain type T, then TTaskReturn must also
        # be of type T. We manually force this via 'type: ignore'.
        artifacts_casted: TTaskReturn = artifacts # type: ignore

        task.artifacts = artifacts_casted
        task.up_to_date = True
        task.built_now = True

        os.chdir(prev_cwd)

        self.current_component = prev_component
        self.current_task = prev_task

        return artifacts_casted
    
    def write_cache(self):
        "Serializes all up-to-date artifacts to a cache file."
        
        cache: BuildCache = {
            "parameters": self.parameters,
            "entries": []
        }

        for component in self._loaded_components.values():
            for task in component.tasks:
                if not task.up_to_date:
                    continue

                cache["entries"].append({
                    "component_name": component.name,
                    "task_name": task.name,
                    "artifacts": task.artifacts,
                    "foreign_files": task.foreign_files,
                    "time": time.time(),
                    "dependencies": [
                        {
                            "component_path": x.origin.path,
                            "task": x.name,
                        }
                        for x in task.known_dependencies
                    ]
                })
    
        json.dump(cache, open("./artifacts/buildcache.json", "w"))

def host():
    "Gets the currently running component host."

    if global_component_host is None:
        raise Exception("There is no component host running.")
    
    return global_component_host