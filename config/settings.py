"""EDCS-Gate settings — single, environment-driven module."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def env_bool(key, default="False"):
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DEBUG", "True")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "apps.accounts", "apps.adminconfig", "apps.validation", "apps.scanners",
    "apps.msgraph", "apps.scheduler", "apps.reports", "apps.notifications",
    "apps.audit", "apps.rbac",'whitenoise.runserver_nostatic',
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.AuditMiddleware",'whitenoise.middleware.WhiteNoiseMiddleware',
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.rbac.context_processors.permissions",
    ]},
}]

if os.getenv("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "edcs_gate"),
        "USER": os.getenv("DB_USER", "edcs"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Celery ─────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", "True")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("SCANNER_TIMEOUT_SECONDS", "600"))

# ── Scanners ───────────────────────────────────────────────────────
DEMO_MODE = env_bool("DEMO_MODE", "True")
ERIDOC_BASE_URL = os.getenv("ERIDOC_BASE_URL", "")
ERIDOC_TOKEN = os.getenv("ERIDOC_TOKEN", "")
BITBUCKET_BASE_URL = os.getenv("BITBUCKET_BASE_URL", "")
BITBUCKET_TOKEN = os.getenv("BITBUCKET_TOKEN", "")

# ── EDCS v1.0.1 scanner engine (vendor/edcs_core, `import edcs`) ───
# The vendored package reads its OWN settings straight from process
# env vars (ERIDOC_REST_URL, BITBUCKET_TOKEN, etc. — see
# vendor/edcs_core/.env.example for the full list). We only need to
# supply sane, cross-platform defaults for the handful of fields that
# otherwise default to hardcoded /var/... Linux paths, so DEMO_MODE=False
# works out of the box on Windows too. Real credentials still come from
# .env — this block never overrides a value the user has already set.
EDCS_VENDOR_DIR = BASE_DIR / "vendor" / "edcs_core"
EDCS_VAR_DIR = BASE_DIR / "var" / "edcs"
if not DEMO_MODE:
    os.environ.setdefault("MANDATORY_DOCS_FILE",
        str(EDCS_VENDOR_DIR / "config" / "mandatory_documents.yaml"))
    os.environ.setdefault("SECRET_RULES_FILE",
        str(EDCS_VENDOR_DIR / "config" / "secret_rules.yaml"))
    os.environ.setdefault("TMP_DIR", str(EDCS_VAR_DIR / "tmp"))
    os.environ.setdefault("CLONE_DIR", str(EDCS_VAR_DIR / "clones"))
    os.environ.setdefault("REPORT_DIR", str(EDCS_VAR_DIR / "reports"))
    os.environ.setdefault("LOG_DIR", str(EDCS_VAR_DIR / "logs"))
    os.environ.setdefault("HISTORY_DB_URL",
        f"sqlite:///{(EDCS_VAR_DIR / 'history.db').as_posix()}")

# ── Microsoft Graph (empty CLIENT_ID → mock mode) ─────────────────
GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
GRAPH_REDIRECT_URI = os.getenv("GRAPH_REDIRECT_URI", "http://localhost:8000/auth/graph/callback")
GRAPH_SCOPES = ["User.Read", "Calendars.ReadWrite"]  # least privilege; offline_access added by MSAL
GRAPH_MOCK = not bool(GRAPH_CLIENT_ID)
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

# ── Scheduler mode ─────────────────────────────────────────────────
# "powerautomate_email": booking sends a structured email that triggers a
#   Power Automate flow which creates the Teams meeting (no Azure AD app
#   registration needed). Status becomes REQUESTED; invitations arrive via
#   the Flow.  ← default (Azure consent not obtainable)
# "graph": original direct Microsoft Graph integration (delegated tokens).
SCHEDULER_MODE = os.getenv("SCHEDULER_MODE", "powerautomate_email")
PA_TRIGGER_MAILBOX = os.getenv("PA_TRIGGER_MAILBOX", "")
PA_SUBJECT_PREFIX = os.getenv("PA_SUBJECT_PREFIX", "[EDCS-GATE-MEETING]")
PA_CANCEL_SUBJECT_PREFIX = os.getenv("PA_CANCEL_SUBJECT_PREFIX", "[EDCS-CANCEL]")

# ── Email (SMTP relay; console backend if unset) ──────────────────
if os.getenv("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", "False")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "edcs-gate-noreply@example.com")

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
