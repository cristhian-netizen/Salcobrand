FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/app/backend DATA_DIR=/data/app PORT=8080 \
    NEURAVISION_ANALYSIS_BACKEND=remote NEURAVISION_WARMUP=0 \
    ROLE=all APIS_STORE=memory APIS_CW_METRICS=0
WORKDIR /srv
COPY deploy/kilby/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY app/backend /srv/app/backend
COPY app/frontend /srv/app/frontend
COPY deploy/kilby /srv/deploy/kilby
RUN mkdir -p /data
EXPOSE 8080
CMD ["python", "/srv/deploy/kilby/start_backend.py"]
