from pathlib import Path
from config.settings import *

source = Path.home() / "edcs-data-migration" / "source.sqlite3"
if not source.is_file():
    raise RuntimeError("Source database does not exist: %s" % source)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": source.as_uri() + "?mode=ro",
        "OPTIONS": {"uri": True},
    }
}
