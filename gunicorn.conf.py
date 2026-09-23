"""Gunicorn configuration, loaded automatically from the working directory.

Only the telemetry hook lives here; the server settings stay in the Dockerfile's CMD.
"""


def post_fork(server, worker):
    # after the fork: the OTLP exporters' threads must start in the worker (project/telemetry.py)
    from project.telemetry import setup

    setup()
