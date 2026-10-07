# Share the compiler pin with host builds; schema validation checks this line against the packaged toolchain manifest.
FROM drpsychick/texlive-pdflatex@sha256:55b4bef7344394c0aafcd69b1796280f64b871ee2d2f2c3115e8f93ec9fea6ea AS texlive

FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS runtime

# The upstream TeX binaries use musl; Python wheels use Debian's glibc.
RUN apt-get update \
    && apt-get install --no-install-recommends -y firefox-esr musl tini=0.19.0-1+b3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 resumeme \
    && mkdir /workspace \
    && chown resumeme:resumeme /workspace

# Carry TeX into the runtime so document generation never needs a host Docker socket or a nested daemon.
COPY --from=texlive /usr/local/texlive /usr/local/texlive

# Keep transient caches writable under an arbitrary caller UID while mounted workspace files retain caller ownership.
ENV PATH="/opt/venv/bin:/usr/local/texlive/bin/x86_64-linuxmusl:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESUMEME_TEX_BACKEND=local \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace

# Reap orphaned subprocesses and forward shutdown signals to the CLI's process group.
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "resumeme"]
CMD ["--help"]

FROM runtime AS builder

# Build tooling lives outside the runtime venv, letting the final stage copy application dependencies without Poetry.
RUN python -m pip install --no-cache-dir poetry==2.5.1 \
    && python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_KEYRING_ENABLED=false \
    POETRY_INSTALLER_RE_RESOLVE=false
WORKDIR /opt/build

# Cache the locked dependency layer independently of Python source edits, and install the application as a distributable wheel.
COPY pyproject.toml poetry.lock README.md LICENSE ./
RUN poetry check --lock \
    && poetry install --only main --no-root --no-interaction --no-ansi
COPY pkg/resumeme ./pkg/resumeme
RUN poetry build --format wheel \
    && python -m pip install --no-cache-dir --no-deps dist/*.whl

FROM builder AS development

# Development keeps source and validation tools; it is a separate target and is never the image published by CI.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN poetry install --with dev --no-interaction --no-ansi \
    && ln -s /opt/venv .venv \
    && chown -R resumeme:resumeme /opt/build /opt/venv
USER 10001:10001

FROM runtime AS production

# Copy only the installed environment; build context files, tests, and development tools stay out of production layers.
COPY --from=builder /opt/venv /opt/venv
LABEL org.opencontainers.image.title="resumeme" \
    org.opencontainers.image.description="Build an illustrated LinkedIn resume from versioned profile inputs" \
    org.opencontainers.image.licenses="GPL-3.0-only"
USER 10001:10001
