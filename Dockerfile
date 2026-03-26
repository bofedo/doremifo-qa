FROM ghcr.io/mtg/essentia:latest

RUN apt-get update && apt-get install -y \
    python3-pip \
    sox \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    fastapi \
    uvicorn \
    python-multipart \
    numpy \
    pandas \
    scipy \
    scikit-learn \
    statsmodels \
    pingouin

WORKDIR /app
COPY analyze_cell.py .
COPY analyze_cawi.py .
COPY app.py .

RUN mkdir -p /app/data/references /app/data/archive /app/data/analysis

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
