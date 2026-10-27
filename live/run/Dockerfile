# The live judge page for Receipts, as a Cloud Run service. The build context is made by
# live/run/build.py: the receipts package and the recorded inputs of the five preset tasks.
FROM python:3.12-slim
# The sandbox executor keeps each branch's files in git on the host.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app
COPY --chown=user . /app
RUN pip install --no-cache-dir .
USER user
# Fetch and check the pinned busybox now, so a run never waits on busybox.net.
RUN python -c "from receipts.sandbox.busybox import load_busybox; load_busybox()"
# Cloud Run sets PORT (8080).
ENV RECEIPTS_REPO=/app
CMD ["python", "-m", "receipts.live"]
