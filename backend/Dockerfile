FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=300 \
    PYTHONUNBUFFERED=1 \
    SPACY_MODEL=en_core_web_sm

# WeasyPrint runtime deps (pango, cairo, fonts)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libcairo2 \
      libffi-dev \
      fonts-dejavu \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# requirements-evals.txt (ragas/datasets/langchain-*) is intentionally NOT
# installed here. Eval execution runs in a separate worker; the main API
# image stays slim for Render's 512 MB free tier.
RUN pip install --no-cache-dir -r requirements.txt

# Small spaCy model in production to stay within Railway's memory limits.
# Local dev can override with: docker build --build-arg SPACY_MODEL=en_core_web_lg
ARG SPACY_MODEL=en_core_web_sm
RUN python -m spacy download "${SPACY_MODEL}"

COPY . .
RUN chmod +x ./start.sh

EXPOSE 8000
CMD ["./start.sh"]
