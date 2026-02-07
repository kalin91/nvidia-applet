"""Setup GTK stubs for type checking."""

import subprocess
import sys


def main() -> None:
    """Setup GTK stubs for type checking."""
    # run pip install pygobject-stubs --no-cache-dir --config-settings=config=Gtk3,Gdk3,Soup2
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "pygobject-stubs",
            "--no-cache-dir",
            "--config-settings=config=Gtk3,Gdk3,Soup2",
        ]
    )


if __name__ == "__main__":
    main()
