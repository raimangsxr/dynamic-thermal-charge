ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
FROM ${PYTHON_BASE_IMAGE}

ARG DTC_BUILD_VERSION=dev
ARG DTC_VCS_REF=unknown
ARG DTC_BUILD_DATE=unknown
ARG DTC_LOCK_SHA256=unknown
ARG COINOR_CBC_VERSION=2.10.12+ds-1

WORKDIR /app
RUN install -d -m 0755 /run/dynamic-thermal-charge
COPY pyproject.toml README.md requirements.lock build-requirements.lock ./
COPY src ./src
COPY entrypoint.sh /usr/local/bin/dynamic-thermal-charge-entrypoint
RUN apt-get update \
    && apt-get install -y --no-install-recommends "coinor-cbc=${COINOR_CBC_VERSION}" \
    && install -d -m 0755 /usr/share/dynamic-thermal-charge \
    && dpkg-query -W -f='${Package}=${Version}\n' coinor-cbc > /usr/share/dynamic-thermal-charge/cbc-package.txt \
    && test "$(cat /usr/share/dynamic-thermal-charge/cbc-package.txt)" = "coinor-cbc=${COINOR_CBC_VERSION}" \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r build-requirements.lock \
    && python -m pip install --no-cache-dir --no-build-isolation --require-hashes -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps "."
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.version="$DTC_BUILD_VERSION" \
      org.opencontainers.image.revision="$DTC_VCS_REF" \
      org.opencontainers.image.created="$DTC_BUILD_DATE" \
      io.dynamic-thermal-charge.dependencies-lock-sha256="$DTC_LOCK_SHA256" \
      io.dynamic-thermal-charge.cbc-version="$COINOR_CBC_VERSION" \
      io.dynamic-thermal-charge.cbc-record="/usr/share/dynamic-thermal-charge/cbc-package.txt"
ENTRYPOINT ["/usr/local/bin/dynamic-thermal-charge-entrypoint"]
CMD ["python", "-c", "from dynamic_thermal_charge.entrypoints import run_controller; run_controller()"]
