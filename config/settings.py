"""Django settings for the GeM bid automation application."""
import os
from pathlib import Path
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Populate os.environ from a .env file; real environment variables win."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "drf_spectacular", "django_filters", "apps.companies", "apps.bids.apps.BidsConfig", "apps.documents",
    "apps.processing", "apps.generation", "apps.common",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("DATABASE_URL"):
    import dj_database_url
    DATABASES = {"default": dj_database_url.config(default=os.getenv("DATABASE_URL"), conn_max_age=600)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # Let SQLite wait for a short-lived web/worker write before failing.
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 30
    # SQLite serializes writes; parallel Celery processes otherwise contend on
    # the same database while recording document processing status.
    CELERY_WORKER_CONCURRENCY = max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", "1")))
else:
    CELERY_WORKER_CONCURRENCY = max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", str(os.cpu_count() or 1))))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "storage"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_ACTIVE_BID_LIMIT = max(1, min(500, int(os.getenv("DEFAULT_ACTIVE_BID_LIMIT", "1"))))
ACTIVE_BID_EXPIRY_DAYS = max(1, min(3650, int(os.getenv("ACTIVE_BID_EXPIRY_DAYS", "30"))))
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "bid-dashboard"
LOGOUT_REDIRECT_URL = "login"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "GeM Bid Workspace <webmaster@localhost>")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
    EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "0") == "1"
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
else:
    # Local development remains usable without an SMTP server; reset emails
    # (including their one-time links) are written to the application console.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "0") == "1"
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication", "rest_framework.authentication.BasicAuthentication"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend", "rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination", "PAGE_SIZE": 25,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "GeM Bid Automation API",
    "DESCRIPTION": "Authenticated API for bid uploads and processing status.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-bids-daily": {
        "task": "apps.bids.tasks.cleanup_expired_bids",
        "schedule": crontab(hour=3, minute=0),
    },
}
