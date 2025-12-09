FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY monitor.py .

# Run as non-root user
RUN useradd -m -u 1000 monitor
USER monitor

CMD ["python", "-u", "monitor.py"]
