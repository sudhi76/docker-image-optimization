| Variant | Size | Gzipped | Layers | OS packages | CVEs (C/H/M/L) | Shell | User | Rebuild after code change | Startup | Graceful stop | Smoke tests |
|---|--:|--:|--:|--:|--:|:-:|---|--:|--:|--:|:-:|
| `01-naive` | 1107.3 MB | 349.6 MB | 10 | 208 | 1/173/520/923 | yes | root | 10.3 s | 130 ms | 0.1 s | pass |
| `02-multistage` | 159.8 MB | 57.3 MB | 2 | 78 | 0/48/75/64 | yes | root | 6.8 s | 102 ms | 0.1 s | pass |
| `03-alpine` | 19.6 MB | 7.9 MB | 3 | 18 | 0/0/1/0 | yes | 10001 | 1.5 s | 100 ms | 0.1 s | pass |
| `04-distroless` | 12.6 MB | 4.5 MB | 14 | 6 | 0/0/0/0 | no | 65532 | 1.6 s | 113 ms | 0.1 s | pass |
| `05-scratch` | 9.9 MB | 3.8 MB | 2 | 0 | 0/0/0/0 | no | 65532:65532 | 1.6 s | 106 ms | 0.1 s | pass |

Measured 2026-11-11 on linux/arm64 (Darwin host), Docker 29.5.2, Trivy 0.76.2. Size is the unpacked filesystem; gzipped approximates the download. CVE counts change daily as new vulnerabilities are published.
