# The accuracy dashboard's scoring harness (design §11.7): the one place a simulation is compared
# with a measured end-to-end benchmark. Built and signed by .github/workflows/harness-release.yml
# from a release tag, and named by its digest. Build context: the repository root.
#
#   docker build --platform linux/amd64 -f harness/Dockerfile .
#
# The image holds the scorer (orchestrator/), the JSON Schemas it validates against (schemas/;
# contract.py and validate_summary_v2.py read them from beside orchestrator/), and the tools to
# build a simulator: git and the Go toolchain inference-sim's go.mod names. It holds no
# simulator; run.sh clones and builds the one its caller names, so one image scores any simulator
# build.

# python:3.13-slim-bookworm, by the digest of its multi-platform index on 2026-11-05.
FROM --platform=linux/amd64 python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f

# The Go release inference-sim's go.mod states (go 1.27.2), checked against go.dev's sha256.
ARG GO_VERSION=1.27.2
ARG GO_SHA256=ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSLo /tmp/go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" \
 && echo "${GO_SHA256}  /tmp/go.tgz" | sha256sum -c - \
 && tar -C /usr/local -xzf /tmp/go.tgz \
 && rm /tmp/go.tgz

ENV PATH=/usr/local/go/bin:$PATH \
    GOTOOLCHAIN=local \
    GOFLAGS=-mod=readonly

COPY harness/requirements.txt /harness/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /harness/requirements.txt

COPY orchestrator /harness/orchestrator
COPY schemas /harness/schemas
COPY harness/run.sh /harness/harness/run.sh
WORKDIR /harness

ENTRYPOINT ["/harness/harness/run.sh"]
