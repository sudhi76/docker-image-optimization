#!/usr/bin/env python3
"""Build every Dockerfile variant, measure it, smoke-test it and write a report.

Usage: python3 scripts/benchmark.py [variant ...]

Needs docker (with BuildKit) and trivy on PATH. Standard library only.
Writes results/results.json and results/results.md, and updates the table in
README.md between the results markers. Exits non-zero if any variant fails a
smoke test.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DOCKERFILES = ROOT / "dockerfiles"
RESULTS = ROOT / "results"
README = ROOT / "README.md"


def run(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, text=True, capture_output=True, **kwargs)


def build(tag, dockerfile, context):
    """Build an image and return the wall-clock seconds it took."""
    start = time.monotonic()
    result = run(
        "docker", "build", "--quiet",
        "--build-arg", "VERSION=benchmark",
        "--file", str(dockerfile), "--tag", tag, str(context),
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"build of {tag} failed:\n{result.stderr}")
    return time.monotonic() - start


def rebuild_after_code_change(tag, dockerfile):
    """Time a rebuild after a one-line change to main.go, with a warm cache."""
    with tempfile.TemporaryDirectory() as tmp:
        context = Path(tmp) / "app"
        shutil.copytree(APP, context)
        build(tag + "-rebuild", dockerfile, context)  # warm the cache for this context
        with open(context / "main.go", "a") as f:
            f.write(f"\n// rebuild {time.time_ns()}\n")
        seconds = build(tag + "-rebuild", dockerfile, context)
    run("docker", "rmi", tag + "-rebuild", check=False)
    return seconds


def filesystem_size(tag):
    """Return (unpacked, gzipped) bytes of the image's filesystem.

    docker image inspect reports the compressed size with the containerd image
    store and the unpacked size with overlay2, so measure the filesystem itself.
    """
    cid = run("docker", "create", tag).stdout.strip()
    unpacked = gzipped = 0
    gz = zlib.compressobj(6, zlib.DEFLATED, 31)
    try:
        with subprocess.Popen(["docker", "export", cid], stdout=subprocess.PIPE) as proc:
            while chunk := proc.stdout.read(1 << 20):
                unpacked += len(chunk)
                gzipped += len(gz.compress(chunk))
        gzipped += len(gz.flush())
    finally:
        run("docker", "rm", cid, check=False)
    return unpacked, gzipped


def inspect(tag):
    info = json.loads(run("docker", "image", "inspect", tag).stdout)[0]
    unpacked, gzipped = filesystem_size(tag)
    has_shell = run("docker", "run", "--rm", "--entrypoint", "/bin/sh", tag, "-c", "true", check=False).returncode == 0
    return {
        "size_mb": round(unpacked / 1_000_000, 1),
        "gzip_mb": round(gzipped / 1_000_000, 1),
        "layers": len(info["RootFS"]["Layers"]),
        "user": info["Config"].get("User") or "root",
        "shell": has_shell,
    }


def http_get(url):
    with urllib.request.urlopen(url, timeout=2) as resp:
        return resp.status, resp.read().decode()


def run_container(tag):
    """Start the image, then measure startup, smoke-test it and time a graceful stop."""
    started = time.monotonic()
    cid = run("docker", "run", "--detach", "--publish", "127.0.0.1::8080", tag).stdout.strip()
    checks = {}
    try:
        port = run("docker", "port", cid, "8080/tcp").stdout.split(":")[-1].strip()
        base = f"http://127.0.0.1:{port}"

        startup_ms = None
        deadline = started + 15
        while time.monotonic() < deadline:
            try:
                if http_get(base + "/healthz")[0] == 200:
                    startup_ms = round((time.monotonic() - started) * 1000)
                    break
            except OSError:
                pass
            time.sleep(0.02)
        checks["healthz"] = startup_ms is not None

        try:
            status, body = http_get(base + "/time?tz=Asia/Kolkata")
            checks["time zone"] = status == 200 and json.loads(body).get("tz") == "Asia/Kolkata"
        except OSError as err:
            checks["time zone"] = False
            print(f"  /time failed: {err}", file=sys.stderr)

        try:
            checks["metrics"] = "timeapi_requests_total" in http_get(base + "/metrics")[1]
        except OSError:
            checks["metrics"] = False

        # The image's own HEALTHCHECK, which must work without a shell.
        healthy = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = run("docker", "inspect", "--format", "{{.State.Health.Status}}", cid).stdout.strip()
            if status in ("healthy", "unhealthy"):
                healthy = status == "healthy"
                break
            time.sleep(0.25)
        checks["HEALTHCHECK"] = healthy

        stop_start = time.monotonic()
        run("docker", "stop", "--time", "10", cid)
        stop_s = round(time.monotonic() - stop_start, 1)
    finally:
        if not checks.get("healthz"):
            print(run("docker", "logs", cid, check=False).stdout, file=sys.stderr)
        run("docker", "rm", "--force", cid, check=False)

    return {"startup_ms": startup_ms, "stop_s": stop_s, "checks": checks}


def scan(tag):
    """Count OS packages, Go modules and known vulnerabilities with Trivy."""
    report = json.loads(run(
        "trivy", "image", "--quiet", "--scanners", "vuln", "--list-all-pkgs",
        "--format", "json", tag,
    ).stdout)
    os_pkgs = lang_pkgs = 0
    vulns = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    seen = set()
    for result in report.get("Results", []):
        count = len(result.get("Packages") or [])
        if result.get("Class") == "os-pkgs":
            os_pkgs += count
        else:
            lang_pkgs += count
        for v in result.get("Vulnerabilities") or []:
            key = (v["VulnerabilityID"], v["PkgName"])
            if key not in seen and v["Severity"] in vulns:
                seen.add(key)
                vulns[v["Severity"]] += 1
    return {"os_packages": os_pkgs, "go_modules": lang_pkgs, "vulns": vulns}


def to_markdown(results, meta):
    yes_no = lambda b: "yes" if b else "no"
    lines = [
        "| Variant | Size | Gzipped | Layers | OS packages | CVEs (C/H/M/L) | Shell | User | Rebuild after code change | Startup | Graceful stop | Smoke tests |",
        "|---|--:|--:|--:|--:|--:|:-:|---|--:|--:|--:|:-:|",
    ]
    for r in results:
        v = r["vulns"]
        failed = [name for name, ok in r["checks"].items() if not ok]
        lines.append(
            f"| `{r['variant']}` | {r['size_mb']} MB | {r['gzip_mb']} MB | {r['layers']} | {r['os_packages']} | "
            f"{v['CRITICAL']}/{v['HIGH']}/{v['MEDIUM']}/{v['LOW']} | {yes_no(r['shell'])} | {r['user']} | "
            f"{r['rebuild_s']:.1f} s | {r['startup_ms']} ms | {r['stop_s']} s | "
            f"{'pass' if not failed else 'FAIL: ' + ', '.join(failed)} |"
        )
    lines += [
        "",
        f"Measured {meta['date']} on {meta['platform']}, Docker {meta['docker']}, Trivy {meta['trivy']}. "
        "Size is the unpacked filesystem; gzipped approximates the download. CVE counts change daily as new vulnerabilities are published.",
    ]
    return "\n".join(lines) + "\n"


def main():
    only = set(sys.argv[1:])
    variants = sorted(p for p in DOCKERFILES.glob("*.Dockerfile") if not only or p.stem in only)
    if not variants:
        sys.exit("no matching Dockerfiles")

    # Trivy talks to the Docker API directly, so point it at the CLI's current context (Colima, Docker Desktop, ...).
    if "DOCKER_HOST" not in os.environ:
        host = run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}", check=False).stdout.strip()
        if host:
            os.environ["DOCKER_HOST"] = host

    results = []
    for dockerfile in variants:
        name = dockerfile.stem
        tag = f"timeapi:{name}"
        print(f"== {name}", file=sys.stderr)
        build(tag, dockerfile, APP)
        result = {"variant": name, **inspect(tag)}
        result["rebuild_s"] = round(rebuild_after_code_change(tag, dockerfile), 1)
        result.update(run_container(tag))
        result.update(scan(tag))
        print(f"   {result['size_mb']} MB, checks {result['checks']}", file=sys.stderr)
        results.append(result)

    meta = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "platform": f"linux/{run('docker', 'version', '--format', '{{.Server.Arch}}').stdout.strip()}"
                    + (" (GitHub Actions)" if os.environ.get("GITHUB_ACTIONS") else f" ({platform.system()} host)"),
        "docker": run("docker", "version", "--format", "{{.Server.Version}}").stdout.strip(),
        "trivy": re.search(r"Version: (\S+)", run("trivy", "--version").stdout).group(1),
    }
    table = to_markdown(results, meta)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2) + "\n")
    (RESULTS / "results.md").write_text(table)
    if not only and README.exists():
        text = README.read_text()
        new = re.sub(
            r"(<!-- results:start -->\n).*?(<!-- results:end -->)",
            lambda m: m.group(1) + table + m.group(2),
            text, flags=re.S,
        )
        README.write_text(new)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write("## Image comparison\n\n" + table)

    print(table)
    failed = [r["variant"] for r in results if not all(r["checks"].values())]
    if failed:
        sys.exit(f"smoke tests failed for: {', '.join(failed)}")


if __name__ == "__main__":
    main()
