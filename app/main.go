// Command timeapi is a small HTTP service used to compare container images.
// It reports the time in a given time zone and exposes Prometheus metrics,
// which exercises two things minimal images often lack: time zone data and
// a way to run a health check without a shell or curl.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// version is set at build time with -ldflags "-X main.version=...".
var version = "dev"

var requests = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "timeapi_requests_total",
	Help: "HTTP requests by handler and status code.",
}, []string{"handler", "code"})

func main() {
	healthcheck := flag.Bool("healthcheck", false, "probe /healthz on the local server and exit 0 if healthy")
	flag.Parse()

	addr := ":" + envOr("PORT", "8080")

	// Images without a shell cannot run curl in HEALTHCHECK, so the binary checks itself.
	if *healthcheck {
		if err := probe("http://127.0.0.1" + addr + "/healthz"); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	srv := &http.Server{
		Addr:              addr,
		Handler:           newMux(),
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("listening", "addr", addr, "version", version)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server failed", "err", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("shutdown failed", "err", err)
		os.Exit(1)
	}
}

func newMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", counted("healthz", healthz))
	mux.HandleFunc("GET /time", counted("time", timeIn))
	mux.Handle("GET /metrics", promhttp.Handler())
	return mux
}

func healthz(w http.ResponseWriter, _ *http.Request) int {
	return writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "version": version})
}

// timeIn returns the current time in the zone given by ?tz=, for example Asia/Kolkata.
// It fails on images that ship no time zone database.
func timeIn(w http.ResponseWriter, r *http.Request) int {
	name := r.URL.Query().Get("tz")
	if name == "" {
		name = "UTC"
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		return writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	return writeJSON(w, http.StatusOK, map[string]string{
		"tz":   loc.String(),
		"time": time.Now().In(loc).Format(time.RFC3339),
	})
}

func counted(name string, h func(http.ResponseWriter, *http.Request) int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := h(w, r)
		requests.WithLabelValues(name, fmt.Sprint(code)).Inc()
	}
}

func writeJSON(w http.ResponseWriter, code int, body any) int {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
	return code
}

func probe(url string) error {
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unhealthy: %s", resp.Status)
	}
	return nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
