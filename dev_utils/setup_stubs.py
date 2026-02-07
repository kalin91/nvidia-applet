"""Setup GTK stubs for type checking."""

import pip


def main() -> None:
    """Setup GTK stubs for type checking."""
    # run pip install pygobject-stubs --no-cache-dir --config-settings=config=Gtk3,Gdk3,Soup2
    pip_args = [
        "install",
        "pygobject-stubs",
        "--no-cache-dir",
        "--config-settings=config=Gtk3,Gdk3,Soup2",
    ]
    pip.main(pip_args)


if __name__ == "__main__":
    main()
