FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY app ./app
COPY canonical_verifier_selftest.py ./canonical_verifier_selftest.py
RUN python ./canonical_verifier_selftest.py
COPY resolver_patch_atlas.py /tmp/resolver_patch_atlas.py
RUN python /tmp/resolver_patch_atlas.py && rm /tmp/resolver_patch_atlas.py
COPY resolver_patch_atlas_v13.py /tmp/resolver_patch_atlas_v13.py
RUN python /tmp/resolver_patch_atlas_v13.py && rm /tmp/resolver_patch_atlas_v13.py
COPY resolver_patch_atlas_v14.py /tmp/resolver_patch_atlas_v14.py
RUN python /tmp/resolver_patch_atlas_v14.py && rm /tmp/resolver_patch_atlas_v14.py
COPY resolver_patch_atlas_v15.py /tmp/resolver_patch_atlas_v15.py
RUN python /tmp/resolver_patch_atlas_v15.py && rm /tmp/resolver_patch_atlas_v15.py
COPY resolver_patch_atlas_v16.py /tmp/resolver_patch_atlas_v16.py
RUN python /tmp/resolver_patch_atlas_v16.py && rm /tmp/resolver_patch_atlas_v16.py
COPY resolver_patch_atlas_v17.py /tmp/resolver_patch_atlas_v17.py
RUN python /tmp/resolver_patch_atlas_v17.py && rm /tmp/resolver_patch_atlas_v17.py
COPY resolver_patch_atlas_v18.py /tmp/resolver_patch_atlas_v18.py
RUN python /tmp/resolver_patch_atlas_v18.py && rm /tmp/resolver_patch_atlas_v18.py
COPY resolver_patch_atlas_v19.py /tmp/resolver_patch_atlas_v19.py
RUN python /tmp/resolver_patch_atlas_v19.py && rm /tmp/resolver_patch_atlas_v19.py
COPY resolver_patch_atlas_v20.py /tmp/resolver_patch_atlas_v20.py
RUN python /tmp/resolver_patch_atlas_v20.py && rm /tmp/resolver_patch_atlas_v20.py
COPY resolver_patch_atlas_v21.py /tmp/resolver_patch_atlas_v21.py
RUN python /tmp/resolver_patch_atlas_v21.py && rm /tmp/resolver_patch_atlas_v21.py
COPY resolver_patch_atlas_v22.py /tmp/resolver_patch_atlas_v22.py
RUN python /tmp/resolver_patch_atlas_v22.py && rm /tmp/resolver_patch_atlas_v22.py
COPY resolver_patch_atlas_v23.py /tmp/resolver_patch_atlas_v23.py
RUN python /tmp/resolver_patch_atlas_v23.py && rm /tmp/resolver_patch_atlas_v23.py
COPY resolver_patch_atlas_v24.py /tmp/resolver_patch_atlas_v24.py
RUN python /tmp/resolver_patch_atlas_v24.py && rm /tmp/resolver_patch_atlas_v24.py
COPY resolver_patch_atlas_v25.py /tmp/resolver_patch_atlas_v25.py
RUN python /tmp/resolver_patch_atlas_v25.py && rm /tmp/resolver_patch_atlas_v25.py
COPY resolver_patch_atlas_v26.py /tmp/resolver_patch_atlas_v26.py
RUN python /tmp/resolver_patch_atlas_v26.py && rm /tmp/resolver_patch_atlas_v26.py
COPY resolver_patch_atlas_v27.py /tmp/resolver_patch_atlas_v27.py
RUN python /tmp/resolver_patch_atlas_v27.py && rm /tmp/resolver_patch_atlas_v27.py
COPY resolver_patch_atlas_v28.py /tmp/resolver_patch_atlas_v28.py
RUN python /tmp/resolver_patch_atlas_v28.py && rm /tmp/resolver_patch_atlas_v28.py
COPY resolver_patch_atlas_v29.py /tmp/resolver_patch_atlas_v29.py
RUN python /tmp/resolver_patch_atlas_v29.py && rm /tmp/resolver_patch_atlas_v29.py
COPY resolver_patch_atlas_v30.py /tmp/resolver_patch_atlas_v30.py
RUN python /tmp/resolver_patch_atlas_v30.py && rm /tmp/resolver_patch_atlas_v30.py
COPY resolver_patch_atlas_v31.py /tmp/resolver_patch_atlas_v31.py
RUN python /tmp/resolver_patch_atlas_v31.py && rm /tmp/resolver_patch_atlas_v31.py

RUN mkdir -p /data
ENV CACHE_DB=/data/resolver_cache.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Carly v51 gives visible-vehicle detail questions outermost precedence and
# removes unstated household-size assumptions from family wording.
CMD uvicorn app.main_v51:app --host 0.0.0.0 --port ${PORT:-8000}
