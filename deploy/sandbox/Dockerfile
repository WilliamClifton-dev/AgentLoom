FROM python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes \
        --requirement /tmp/requirements.lock \
    && rm /tmp/requirements.lock

WORKDIR /workspace
USER 65534:65534
