FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY app ./app
COPY resolver_patch_atlas.py /tmp/resolver_patch_atlas.py
RUN python /tmp/resolver_patch_atlas.py && rm /tmp/resolver_patch_atlas.py
COPY resolver_patch_atlas_v13.py /tmp/resolver_patch_atlas_v13.py
RUN python /tmp/resolver_patch_atlas_v13.py && rm /tmp/resolver_patch_atlas_v13.py
COPY resolver_patch_atlas_v14.py /tmp/resolver_patch_atlas_v14.py
RUN python /tmp/resolver_patch_atlas_v14.py && rm /tmp/resolver_patch_atlas_v14.py

RUN mkdir -p /data
ENV CACHE_DB=/data/resolver_cache.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
