FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY monitor.py .

# Create directories for volumes (will be mounted over)
RUN mkdir -p /keystore /data

CMD ["python", "-u", "monitor.py"]
