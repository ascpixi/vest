# 🦺 Vest
[![image](https://img.shields.io/pypi/v/vest-build.svg)](https://pypi.python.org/pypi/vest-build)
[![image](https://img.shields.io/pypi/l/vest-build.svg)](https://github.com/ascpixi/vest/blob/master/LICENSE)
[![image](https://img.shields.io/pypi/pyversions/vest-build.svg)](https://pypi.python.org/pypi/vest-build)
[![Actions status](https://github.com/ascpixi/vest/workflows/CI/badge.svg)](https://github.com/ascpixi/vest/actions)

Vest is a Python-based build system for bespoke use.

## Getting started
First, install Vest from PyPI:
```
pip install vest-build
```

Then, create a `build.vest` file! What this file will do depends on your project. Let's say you're building a C project. In this case, your `.vest` file might look like this:

```py
from vest import *

component(
    name = "my-c-project"
)

@task
def build():
    # Let's turn each C file to an object file...
    for (src, dst) in build_list(
        src = "./src/**/*.c",
        dst = "./obj",
        ext = ".o",
        flatten = True
    ):
        run("gcc", ["-c", src, "-o", dst])

    # ...then link em' all!
    run("gcc", [
        "-o", "./bin/final",
        *glob("./obj/*.o")
    ])

    # Tasks should return all of their final artifacts. This can be a string, list of strings, or a dictionary of strings.
    return "./bin/final"

@task
def run():
    # "run" needs a build to execute!
    artifact = self_dependency(build)

    # Let's run what "build" gave us.
    run(artifact)
```

In the directory you've created the `vest.build` file in, run `vest -t build`.

## Extensions
Vest doesn't assume what languages nor frameworks you're using it for. However, there's a couple of ready PyPI packages for known use-cases:
- [`vest-build-dotnet`](https://github.com/ascpixi/vest-dotnet): support for the .NET SDK.
