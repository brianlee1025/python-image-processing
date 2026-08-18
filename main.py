"""Development entry point.

    python main.py                      # run the Kafka worker
    python main.py sample-card --help   # any other CLI command

The installed console script (`image_processing_service ...`) does the same
thing; this file exists so the service can be run straight from a checkout
without installing the package first, which is what you want while working on
it. Deployments run `image_processing_service.worker` or the console script.
"""

import sys


def main() -> None:
    # No arguments means the thing this service exists to do: consume render
    # requests. Anything else is handed to the full CLI.
    if len(sys.argv) == 1:
        from image_processing_service.worker import run_worker

        run_worker()
        return

    from image_processing_service.cli import app

    app()


if __name__ == "__main__":
    main()
