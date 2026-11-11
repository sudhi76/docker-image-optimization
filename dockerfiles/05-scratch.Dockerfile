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
    go build -trimpath -ldflags="-s -w -X main.version=$VERSION" -tags timetzdata -o /out/timeapi .

# Nothing but the binary. -tags timetzdata embeds the time zone database
# (about 450 KB) because scratch has no /usr/share/zoneinfo.
FROM scratch

# Not needed by this service, but any HTTPS client call fails without it.
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /out/timeapi /timeapi
USER 65532:65532

EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=10s --start-interval=1s CMD ["/timeapi", "-healthcheck"]
ENTRYPOINT ["/timeapi"]
