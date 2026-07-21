import os
from glob import glob

from vest.spec.host import host
from vest.spec.types import ComponentTask
from vest.common.collections import find, single

def restore_task_cache(task: ComponentTask):
    "Restores the cached artifact information related to a task if it exists and is valid."
    cache = host().cache
    if cache is None:
        return # No cache at all - there wasn't a previous invocation

    cache_entry = find(
        cache["entries"],
        lambda x: x["component_name"] == task.origin.name and x["task_name"] == task.name
    )
    
    if cache_entry is None:
        return
    
    def _check_file_invalidated(path: str):
        "Returns `true` if the file at the given path has been changed since the last build."
        return (
            not os.path.exists(path)
            or os.path.getmtime(path) > cache_entry["time"]
            or os.path.getctime(path) > cache_entry["time"]
        )

    # There is a cache entry that corresponds to this task. Check if the
    # sources have changed to see if we have to invalidate it.
    if task.origin.source is not None:
        # The sources are managed by an external repository resolver.
        if _check_file_invalidated(task.origin.path) or task.origin.source.check():
            # The remote repository has updates - all artifacts are thus invalidated.
            return
    else:
        # Validate that the files haven't been modified after the last build timestamp.
        for source_pattern in task.origin.sources:
            for path in glob(
                source_pattern,
                root_dir = task.origin.base_dir,
                recursive = True,
                include_hidden = True,
            ):
                if _check_file_invalidated(os.path.join(task.origin.base_dir, path)):
                    # A file has a "last modified" date more recent than the time when the
                    # cached invocation was executed.
                    return

    # Check if any foreign files (outside of the component's directory) have changed.
    for file in cache_entry["foreign_files"]:
        if _check_file_invalidated(file):
            # One of the foreign files has changed.
            return

    # The cache entry is still valid. None of the files, including the build manifest, have
    # changed since the last build. Given deterministic compilation, another build would
    # result in the exact same artifacts.
    #
    # Check if all of the artifacts returned by the previous build still exist.
    all_exist = True
    artifacts = cache_entry["artifacts"]

    if type(artifacts) is list:
        all_exist = all(os.path.exists(x) for x in artifacts)
    elif type(artifacts) is dict:
        # Dictionaries can either have `str` or `list[str]` values.
        for (key, value) in artifacts.items():
            if type(value) is str:
                if not os.path.exists(value):
                    return
            elif type(value) is list:
                all_exist = all(os.path.exists(x) for x in value)
                if not all_exist:
                    return
            else:
                raise Exception(f"Unknown 'artifacts' dict value type in cache entry for '{cache_entry['component_name']}:{cache_entry['task_name']}'['{key}']: {type(value).__name__}")
    elif type(artifacts) is str:
        all_exist = os.path.exists(artifacts)
    elif artifacts is None:
        all_exist = True
    else:
        raise Exception(f"Unknown 'artifacts' type in cache entry for '{cache_entry['component_name']}:{cache_entry['task_name']}': {type(artifacts).__name__}")

    if not all_exist:
        return

    cached_deps = []

    # Check for dependencies. If any of the dependencies have changed, and they're not marked
    # as up-to-date, this means that we have to invalidate the cache for this task regardless
    # of its sources.
    for dep in cache_entry["dependencies"]:
        dep_component = host().eval_component(dep["component_path"])
        dep_task = single(dep_component.tasks, lambda x: x.name == dep["task"])
        
        if not dep_task.up_to_date or dep_task.built_now:
            # The sources of a dependency have changed (or their artifacts have changed).
            # This means that this component also must be invalidated.
            return
        
        cached_deps.append(dep_task)

    # All checks have succeeded.
    task.up_to_date = True
    task.artifacts = cache_entry["artifacts"]
    task.known_dependencies = cached_deps