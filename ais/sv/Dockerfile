# Build context is the ais/ directory (see docker-compose.yml)
FROM python:3.12-slim
WORKDIR /app
COPY sv/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sv/sv_poller.py sv/sv_probe.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "sv_poller.py"]
