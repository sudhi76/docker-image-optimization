package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func get(t *testing.T, path string) (*httptest.ResponseRecorder, map[string]string) {
	t.Helper()
	rec := httptest.NewRecorder()
	newMux().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	var body map[string]string
	if strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") {
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatalf("decode %s: %v", path, err)
		}
	}
	return rec, body
}

func TestHealthz(t *testing.T) {
	rec, body := get(t, "/healthz")
	if rec.Code != http.StatusOK || body["status"] != "ok" {
		t.Fatalf("got %d %v", rec.Code, body)
	}
}

func TestTimeInZone(t *testing.T) {
	rec, body := get(t, "/time?tz=Asia/Kolkata")
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d %v", rec.Code, body)
	}
	if body["tz"] != "Asia/Kolkata" || !strings.HasSuffix(body["time"], "+05:30") {
		t.Fatalf("unexpected body %v", body)
	}
}

func TestTimeDefaultsToUTC(t *testing.T) {
	_, body := get(t, "/time")
	if body["tz"] != "UTC" {
		t.Fatalf("unexpected body %v", body)
	}
}

func TestTimeUnknownZone(t *testing.T) {
	rec, _ := get(t, "/time?tz=Mars/Olympus")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", rec.Code)
	}
}

func TestMetrics(t *testing.T) {
	get(t, "/healthz")
	rec, _ := get(t, "/metrics")
	if !strings.Contains(rec.Body.String(), `timeapi_requests_total{code="200",handler="healthz"}`) {
		t.Fatal("request counter missing from /metrics")
	}
}
