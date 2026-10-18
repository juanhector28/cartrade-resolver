FROM python:3.11-slim
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "fastapi==0.115.0" "uvicorn==0.30.6" "httpx==0.27.2" "supabase==2.7.4"
RUN mkdir -p /work/app /work/staging && touch /work/app/__init__.py /work/staging/__init__.py
COPY app/deals_api.py /work/app/deals_api.py
COPY staging/api.py /work/staging/api.py
COPY staging/index.html /work/staging/index.html
EXPOSE 8000
CMD ["sh","-c","uvicorn staging.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
