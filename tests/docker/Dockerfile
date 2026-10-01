# Base image for DockerExecutor tests: Python plus git, nothing else.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git procps && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "pytest>=8.2" \
    && git config --system user.email fixture@example.com && git config --system user.name Fixture
CMD ["tail", "-f", "/dev/null"]
