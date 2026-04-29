import os

os.environ.setdefault("GRPC_VERBOSITY", "none")

import logging
import sys

import google.auth
import google.auth.exceptions

from vertex_explorer.ui.overview import Overview


def main():

    try:
        google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        logging.error("no Google credentials found. Run: gcloud auth application-default login")
        sys.exit(1)

    logging.root.handlers.clear()
    Overview().run()


if __name__ == "__main__":
    main()
