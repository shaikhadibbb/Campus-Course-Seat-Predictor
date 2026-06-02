# Dockerfile
# container setup for my backend API

FROM python:3.10-slim

# install system dependencies (psycopg2 needs pg_config or compiler headers sometimes, but psycopg2-binary doesn't. installing anyway to be safe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy all files
COPY . .

# run uvicorn
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
