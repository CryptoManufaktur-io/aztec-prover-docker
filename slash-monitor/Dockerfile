FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .

RUN mkdir -p /keystore

FROM base AS test

COPY test_monitor.py .

CMD ["python", "-m", "unittest", "discover", "-s", "/app", "-p", "test_monitor.py"]

FROM base AS runtime

CMD ["python", "-u", "monitor.py"]
