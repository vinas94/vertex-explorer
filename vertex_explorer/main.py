import os

os.environ.setdefault("GRPC_VERBOSITY", "none")

import logging

from vertex_explorer.ui.app import SchedulesApp


def main():
    logging.root.handlers.clear()
    SchedulesApp().run()


if __name__ == "__main__":
    main()
