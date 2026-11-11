# syntax=docker/dockerfile:1

# Build natively on the build machine and cross-compile for the target platform.
FROM --platform=$BUILDPLATFORM golang:1.27.4 AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .

ARG TARGETOS TARGETARCH VERSION=dev
# Cache mounts keep the module and build caches between builds, so a code
# change recompiles only this package. CGO_ENABLED=0 gives a static binary;
# -trimpath and -s -w drop local paths and debug symbols.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=$VERSION" -o /out/timeapi .

FROM alpine:3.24

# Minimal images leave out time zone data and CA certificates; add them back.
# Versions are not pinned: Alpine removes old package versions from its
# repositories, so pins break builds. The base image tag pins the release.
# hadolint ignore=DL3018
RUN apk add --no-cache ca-certificates tzdata \
    && adduser -D -H -u 10001 app
COPY --from=build /out/timeapi /usr/local/bin/timeapi
USER 10001

EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=10s --start-interval=1s CMD ["timeapi", "-healthcheck"]
ENTRYPOINT ["timeapi"]
