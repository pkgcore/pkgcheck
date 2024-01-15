FROM python:3-slim
ARG PKGCHECK_VERSION

RUN apt-get update && apt-get install -y git && \
    rm -rf /var/lib/apt/lists/ /var/cache/apt && \
    pip install pkgcheck==${PKGCHECK_VERSION} setuptools requests
