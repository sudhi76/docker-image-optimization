# Multi-stage: compile in the Go image, ship only the binary on Debian.
# Dependencies are downloaded in their own layer, so a code change reuses it.
FROM golang:1.27.4 AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o /out/timeapi .

FROM debian:trixie

COPY --from=build /out/timeapi /usr/local/bin/timeapi

EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=10s --start-interval=1s CMD ["timeapi", "-healthcheck"]
CMD ["timeapi"]
