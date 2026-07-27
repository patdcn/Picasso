# Build context is the ais/ directory (see docker-compose.yml)
FROM python:3.12-slim
WORKDIR /app
COPY collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY collector/collector.py .
# seed script + data baked in so seeding is one command in the Dokploy terminal
COPY seed/seed_fleet.py seed/fleet_seed.csv ./seed/
ENV PYTHONUNBUFFERED=1
CMD ["python", "collector.py"]
