import os

os.environ.setdefault("GRPC_VERBOSITY", "none")

from app import SchedulesApp  # noqa: E402


def main() -> None:
    import logging

    _devnull = open(os.devnull, "w")
    for _h in logging.root.handlers:
        if hasattr(_h, "stream"):
            _h.stream = _devnull

    SchedulesApp().run()


if __name__ == "__main__":
    main()
