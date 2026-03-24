FROM ghcr.io/mtg/essentia:latest

# Python závislosti
RUN apt-get update && apt-get install -y \
    python3-pip \
    sox \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    fastapi \
    uvicorn \
    python-multipart

# Kód
WORKDIR /app
COPY analyze_cell.py .
COPY app.py .

# Port
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]