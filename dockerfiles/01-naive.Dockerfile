# The "it works" Dockerfile: one stage, full Go toolchain in the final image,
# runs as root, and COPY . . before building means any code change
# re-downloads every dependency.
FROM golang:1.27.4

WORKDIR /app
COPY . .
RUN go build -o timeapi .

EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=10s --start-interval=1s CMD ["/app/timeapi", "-healthcheck"]
CMD ["/app/timeapi"]
