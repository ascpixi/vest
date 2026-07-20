import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, Protocol, TypeVar

TTaskReturn = TypeVar(
    "TTaskReturn",
    None, # no artifacts
    str, # single artifact
    list[str], # list of unnamed artifacts
    dict[str, str], # named artifacts
    dict[str, list[str]], # named artifacts, where each value is a list
    dict[str, str | list[str]] # named artifacts mix
)

TaskArtifact = None | str | list[str] | dict[str, str | list[str]]

class BuildError(Exception):
    "Represents an error that occurs on behalf of a component."

class UsageError(Exception):
    "Represents an error that has occured because of a usage error (e.g. unspecified parameters)."

@typing.runtime_checkable
class ExternalRepoResolver(Protocol):
    "Represents an object that is capable of fetching files from a remote repository."
   
    def get_directory(self) -> str:
        """
        Gets the directory containing the retrieved files. Implementers of this method
        are highly encouraged to place all retrieved files relative to the directory
        returned by `artifact_dir`.
        """
        ...

    def retrieve(self):
        "Retrieves all files from the remote repository to a local directory, returning its absolute path."
        ...

    def check(self) -> bool:
        "Checks if the retrieval of the remote repository is necessary, returning `True` if it is."
        ...

@dataclass
class Component:
    name: str
    "The unique name of the component."

    path: str
    "The full path to the manifest file declaring the component."

    base_dir: str
    "The base directory of the component."

    source: ExternalRepoResolver | None
    "The resolver to use for external repositories. If `None`, the component is not external."

    sources: list[str]
    "The source files (described by glob patterns) that compose this project."

    cached: bool
    "Whether caching is enabled."

    tasks: list["ComponentTask"] = field(default_factory = list)
    "The tasks registered with the component."

    metadata_entities: list = field(default_factory = list)
    """
    A list of metadata entities associated with this component. Arbitrary Vest extensions may append any kind of object to this field
    to add extended information about the component that would only be of use to external components of said extensions.
    """

@dataclass
class ComponentTask(Generic[TTaskReturn]):
    name: str
    "The name of the task, as defined by the task function's name"

    body: Callable[[], TTaskReturn]
    "The function to invoke to execute the task."

    origin: Component
    "An object representing the component the task was defined in."

    description: str | None
    "A user-friendly description of the task."

    run_script: Callable[[Any], list[str]] | None
    "A function that returns the command to run/debug the artifacts produced by the task."

    artifacts: TTaskReturn | None = None
    """
    The artifacts the task has produced. Do note that this value does not indicate
    whether the task has been invalidated, as a `None` value is a valid artifact type.

    The value of this attribute may potentially originate from a file cache if the
    sources and artifacts have not changed since the last execution of the build system.
    """

    up_to_date: bool = False
    "If `True`, the task has been ran at least once, and its sources haven't changed since its last invocation." 
    
    built_now: bool = False
    "If `True`, the task has been invalidated, and its `up_to_date` status changed in this build invocation."

    known_dependencies: list["ComponentTask"] = field(default_factory = list)
    "The dependencies this task has defined."

    foreign_files: list[str] = field(default_factory = list)
    "The files outside of the component's directory that the task has declared dependencies for."
