#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/build/products/Compositor-zh-CN.app"
if [[ ! -d "$APP" ]]; then echo '请先运行 bash scripts/build.sh'; exit 2; fi
if [[ "${1:-zh}" == en ]]; then
  open -n "$APP" --args -CompositorChineseEnabled NO -AppleLanguages '(en)'
else
  open -n "$APP" --args -CompositorChineseEnabled YES -AppleLanguages '(zh-Hans,en)'
fi
