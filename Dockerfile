FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# System packages the app actually needs at runtime:
#   git       - GitPython (vendor/edcs_core) shells out to `git clone` for
#               the Bitbucket scanner; without it every In-house/Enable/RPA
#               scan errors with "Bad git executable" (the same failure
#               seen when git isn't on PATH on a dev machine).
#   libmagic1 - python-magic (file-type sniffing during document scanning)
#               is a thin wrapper around libmagic; the Python package alone
#               does nothing without this shared library on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libmagic1 \
    && rm -rf /var/lib/apt/lists/*
COPY . .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python manage.py collectstatic --noinput || true
RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
