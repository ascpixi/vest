"""
This module defines parts of the component system specification that are recommended to be used in all Vest components.
This module should only be imported from components, via `from vest import *`.
"""

from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

from vest.spec.core import (
    artifact_dir,
    artifact_dir_path_of,
    clean_artifact_dir,
    artifact_root,
    artifact_root_path_of,
    clean_artifact_root,
    component,
    dependency,
    dependent_on,
    host,
    require_task,
    self_dependency,
    task,
    run,
    run_tool,
    parameter
)

from vest.spec.externals import (
    git_repo,
    GitRepoResolver
)

from vest.spec.types import (
    Component,
    ComponentTask,
    BuildError,
    ExternalRepoResolver
)

from vest.spec.fs import (
    build_list,
    copy,
    copy_many,
    expand_path,
    foreign_file,
    glob,
    make_unique_dir
)

from vest.common.collections import (
    find,
    maybe,
    single,
    flatten
)

from vest.cli import (
    vest_cli,
    VestFailure
)
