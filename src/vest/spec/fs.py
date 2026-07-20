import os
import re
import shutil
from glob import glob as pyglob

from vest.spec.core import host, require_component, require_task

def glob(pattern: str, cwd = False, relative = False) -> list[str]:
    """
    Finds all file paths matching the given glob `pattern`.

    @pattern: The target glob pattern, e.g. `**/*.txt`.
    @cwd: If `True`, the search should be performed in the current working directory. Otherwise, the base directory of the calling component is used.
    @relative: If `True`, the results will be relative paths, as opposed to absolute.
    """

    root = os.getcwd() if cwd else require_component().base_dir
    results = pyglob(pattern, recursive = True, root_dir = root)

    return [
        os.path.join(root, p) if not relative else p
        for p in results
        if not p.endswith(".build") and not os.path.isdir(p)
    ]

def copy(src: str | list[str], dst: str):
    """
    Copies an arbitrary number of files.

    @src: Either a path to a single path, or a list of files to copy.
    @dst: The destination path. If `src` is a list, this must point to a directory.
    """

    if type(src) is list:
        os.makedirs(dst, exist_ok = True) # interpret dst as a directory, *always*
        
        for file in src:
            shutil.copy(file, os.path.join(dst, os.path.basename(file)))
    elif type(src) is str:
        if dst.endswith("/"):
            # If the path ends with a trailing slash, assume it is already a directory
            os.makedirs(dst, exist_ok = True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok = True)

        shutil.copy(src, dst)
    else:
        raise TypeError(f"'src' is of an invalid type '{type(src).__name__}'.")

def copy_many(base: str, files: list[tuple[str | list[str], str]]):
    """
    Copies all files specified in the `files` dictionary, where the keys are
    the source directories (or lists of files to copy), and the values are
    destination paths.
    """

    if os.path.isfile(base):
        raise Exception(f"The copy destination '{base}' is a file - expected either a folder or nothing at all.")
    
    os.makedirs(base, exist_ok = True)

    for (src, dst) in files:
        copy(src, os.path.join(base, dst))

def make_unique_dir(path: str, navigate = False):
    """
    Creates a unique directory, recursively removing an existing one if it exists at
    the specified path. This function calls `os.mkdir` internally.

    @path: The path of the directory to create.
    @navigate: If `True`, the current working directory will be changed to the created directory.
    """
    if os.path.isfile(path):
        raise Exception(f"A file in '{path}' exists, while it was expected to be a directory.")
    
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors = True)

    os.mkdir(path)

    if navigate:
        os.chdir(path)

def build_list(src: str, dst: str, ext: str, flatten = False) -> list[tuple[str, str]]:
    """
    Generates a build list - that is, a list of tuples which specify a file to be
    compiled (as dictated by the given `src` glob pattern) and its output destination.

    If the directory specified by `dst` does not exist, it will be created. All
    sub-directories specified by the second member of the tuples in the returned array
    will also be created, unless `flatten` is set to `True`, which will result in all
    destination paths pointing to files in a single directory.

    When `flatten` is `True`, two files having the same filename in different directories
    will result in an exception informing of the conflict.
    """
    entries: list[tuple[str, str]] = []

    src_fixed_part = re.match(r"(.*?)([*\[\]?+@!].+)", src)
    assert src_fixed_part is not None

    src_fixed_part = src_fixed_part.group(1)

    os.makedirs(dst, exist_ok = True)

    for entry in glob(src, relative = True):
        if flatten:
            entry_dst = os.path.join(dst, os.path.basename(entry))
        else:
            entry_stripped = os.path.relpath(entry, src_fixed_part)
            entry_dst = os.path.join(dst, entry_stripped)
            os.makedirs(os.path.dirname(entry_dst), exist_ok = True)

        entry_dst = os.path.splitext(entry_dst)[0] + ext

        entries.append((entry, entry_dst))
    
    return entries

def expand_path(path: str):
    "Makes path relative to the root of the processed repository absolute."
    return os.path.join(host().repo_dir, path)

def foreign_file(path: str):
    """
    Defines a path, relative to the root of the processed repository, as a foreign file
    dependency, and returns its absolute path.
    """
    abs_path = expand_path(path)
    if abs_path not in require_task().foreign_files:
        require_task().foreign_files.append(abs_path)

    return abs_path