#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "${1:-export}" in
 export)
  xcodebuild -exportLocalizations -project "$ROOT/build/source/Compositor.xcodeproj" \
   -localizationPath "$ROOT/build/xcloc" -exportLanguage zh-Hans \
   -derivedDataPath "$ROOT/build/LocalizationData" ;;
 import)
  test -n "${2:-}" || { echo '用法：bash scripts/xcode-localizations.sh import /绝对路径/zh-Hans.xcloc'; exit 2; }
  xcodebuild -importLocalizations -project "$ROOT/build/source/Compositor.xcodeproj" -localizationPath "$2"
  echo 'Xcode 导入仅修改临时源码；请把审核译文同步回 translations/zh-CN.json，再重新 prepare。' ;;
 *) echo '仅支持 export / import'; exit 2 ;;
esac
