FROM ghcr.io/mtg/essentia:latest

RUN apt-get update && apt-get install -y \
    python3-pip \
    sox \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    fastapi \
    uvicorn \
    python-multipart \
    "numpy==1.19.5" \
    "pandas==1.1.5" \
    "scipy==1.5.4" \
    "scikit-learn==0.24.2" \
    "statsmodels==0.12.2" \
    "pingouin==0.3.12"

WORKDIR /app
COPY analyze_cell.py .
COPY analyze_cawi.py .
COPY app.py .

RUN mkdir -p /app/data/references /app/data/archive /app/data/analysis

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8000"]
