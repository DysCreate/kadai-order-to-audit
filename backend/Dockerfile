FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint needs Pango/HarfBuzz and fonts at runtime; the PDF endpoints fail
# without them even though the Python wheel installs cleanly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libffi8 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV DJANGO_SETTINGS_MODULE=config.settings.production

COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

COPY --chown=10001:10001 . .

# Collect the admin's static files into the image so WhiteNoise can serve them
# without DEBUG. No database connection is needed for collectstatic.
RUN SECRET_KEY=build-only-secret-key-with-at-least-32-chars \
    ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    python manage.py collectstatic --noinput

RUN chmod +x entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home appuser \
    && chown -R 10001:10001 /app
USER 10001

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

# PORT is supplied by Render; Docker Compose and local runs fall back to 8000.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application \
     --bind 0.0.0.0:${PORT:-8000} \
     --workers ${GUNICORN_WORKERS:-1} \
     --threads ${GUNICORN_THREADS:-4} \
     --timeout 120 \
     --access-logfile - \
     --error-logfile -"]
