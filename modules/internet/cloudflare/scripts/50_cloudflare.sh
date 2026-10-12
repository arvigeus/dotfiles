#!/usr/bin/env bash
## Cloudflare WARP prerequisite; registration and runtime control belong to consumers.
set -Eeuo pipefail

systemctl disable warp-svc.service
