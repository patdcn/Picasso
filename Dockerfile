# Slim Python base keeps the image small and the build fast on Contabo's I/O.
FROM python:3.12-slim

# Don't write .pyc files; flush stdout/stderr straight through (better logs in Dokploy).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Install deps first, as their own layer, so code changes don't trigger a full reinstall.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the application code.
COPY app/ ./app/

EXPOSE 8050

# Production server. 2 workers x 4 threads is a sane default for a 6-vCPU box.
# app.main:server  ->  the `server` object inside app/main.py
CMD ["gunicorn", "app.main:server", \
     "--bind", "0.0.0.0:8050", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120"]
