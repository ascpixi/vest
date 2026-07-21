import argparse
from rich.console import Console
import rich.traceback

from vest.cli import VestFailure, vest_cli
from vest.common.log import log_error_hdr

def main():
    console = Console()
    rich.traceback.install()

    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--task", help = "The task to run.", required = True)
    parser.add_argument("-p", "--path", default = "./build.vest", help = "The path to the target component.")
    parser.add_argument("--no-cache", action = "store_true", help = "If set, the results of the previous build will be ignored.")
    args, extra_args = parser.parse_known_args()

    def parse_extra_args():
        transformed: dict[str, str] = {}

        prev_arg: str | None = None
        expecting_key = True

        for arg in extra_args:
            is_key = arg.startswith("-")
            if is_key != expecting_key:
                if expecting_key:
                    # Two keys right next to each other (e.g --type --arch)
                    if prev_arg is not None:
                        log_error_hdr(f"Two or more values specified for parameter {prev_arg}.")
                        exit(1)
                    else:
                        log_error_hdr(f"Stray argument {arg} found.")
                        exit(1)
                else:
                    # Two values right next to each other (e.g. --arch amd64 release)
                    log_error_hdr(f"No value found for parameter {prev_arg}.")
                    exit(1)

            if not expecting_key:
                # There isn't really a possibility where we don't have a previous arg here. We're looking for a value, thus we went over the first iteration
                # (which was looking for a key).
                assert prev_arg is not None

                # This is value! "prev_arg" holds the key, while "arg" holds the value.
                transformed[prev_arg] = arg

            prev_arg = arg
            expecting_key = not expecting_key

        return transformed

    try:
        vest_cli(
            path = args.path,
            task = args.task,
            parameters = parse_extra_args(),
            load_cache = not args.no_cache,
            console = console
        )
    except VestFailure:
        exit(1)

if __name__ == "__main__":
    main()