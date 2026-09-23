import os

from celery import Celery, signals

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

app = Celery("project")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


# OpenTelemetry after the fork, in every worker process and in beat (project/telemetry.py)
@signals.worker_process_init.connect(weak=False)
@signals.beat_init.connect(weak=False)
def _telemetry(**kwargs):
    from project.telemetry import setup

    setup()
