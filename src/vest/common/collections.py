from typing import Callable, Iterable, TypeVar, overload

T = TypeVar("T")
TKey = TypeVar("TKey")
TValue = TypeVar("TValue")

def find(collection: list[T], predicate: Callable[[T], bool]) -> T | None:
    "Finds the first item in the given collection that meets the specified predicate."
    for x in collection:
        if predicate(x):
            return x
    
    return None

def single(collection: list[T], predicate: Callable[[T], bool]) -> T:
    """
    Picks the first item in the given collection that meets the specified predicate.
    If no item meets the predicate, a `LookupError` is raised.
    """
    for x in collection:
        if predicate(x):
            return x
        
    raise LookupError("No value in the given collection matches the predicate.")

@overload
def maybe(value: dict[TKey, TValue], when: bool) -> dict[TKey, TValue]:
    """
    Returns the given `value` if `condition` is `True` - otherwise, returns an empty dictionary.

    This function is useful when defining conditional collection elements:
    ```
    example = {
        "key1": "always present",
        *maybe({ "key2": "sometimes present" }, when = some_condition)
    }
    ```
    """
    ...

@overload
def maybe(value: T | list[T], when: bool) -> list[T]:
    """
    Returns a 1-element list of the given `value` if `condition` is `True` - otherwise,
    returns an empty list. If `value` is a `list`, it is returned instead.

    This function is useful when defining conditional collection elements:
    ```
    example = [
        "always present",
        *maybe("sometimes present", when = some_condition)
    ]
    ```

    ...as opposed to:
    ```
    example = [
        "always present",
        *(["sometimes present"] if some_condition else [])
    ]
    ```
    """
    ...

def maybe(value: T | list[T] | dict[TKey, TValue], when: bool) -> list[T] | dict[TKey, TValue]:
    if isinstance(value, dict):
        return value if when else {}
   
    if not isinstance(value, list):
        return [value] if when else []
    else:
        return value if when else []
    
def flatten(value: Iterable[list[T]]) -> list[T]:
    """
    Flattens a collection of other, nested lists. For example, the sequence `[[1, 2], [3, 4], [5, 6]]`
    becomes `[1, 2, 3, 4, 5, 6]`.
    """
    result: list[T] = []
    for subarr in value:
        result.extend(subarr)
    
    return result