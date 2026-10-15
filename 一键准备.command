#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 scripts/localize.py prepare
printf '\n已生成 build/source 和 reports。安装完整 Xcode 后运行 bash scripts/build.sh。\n'
