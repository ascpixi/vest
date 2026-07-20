import os

def walk_down(start_path: str, end_path: str):
    """
    Returns the paths to traverse when walking down a directory tree, starting at
    `start_path`, and ending with `end_path`.

    @start_path: The path to being traversal in. Must be a child of `end_path`.
    @end_path: The path to end traversing directories on. Must be a parent of `start_path`.
    """

    start_path = os.path.abspath(start_path)
    end_path = os.path.abspath(end_path)

    if not start_path.startswith(end_path):
        raise ValueError(f"End path '{end_path}' is not a parent of start path '{start_path}'")

    current_path = start_path
    paths = [current_path]
    
    while current_path != end_path:
        if current_path == os.path.dirname(current_path): # We've reached the root
            raise ValueError(f"Reached root directory before finding end path '{end_path}'")
        
        current_path = os.path.dirname(current_path)
        paths.append(current_path)
    
    return paths
