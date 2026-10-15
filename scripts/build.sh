#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/build/logs" "$ROOT/build/products"
if ! xcodebuild -version > "$ROOT/build/logs/xcode-version.txt" 2>&1; then
  echo '需要完整 Xcode 26 或更新版本。当前仅有 Command Line Tools 或未选择完整 Xcode。'
  echo '安装并首次打开 Xcode 后，运行：sudo xcode-select -s /Applications/Xcode.app/Contents/Developer'
  exit 2
fi
python3 "$ROOT/scripts/localize.py" prepare
# Keep module/executable names intact; isolate the bundle identity and final app filename.
xcodebuild -project "$ROOT/build/source/Compositor.xcodeproj" -scheme Compositor \
  -configuration Release -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath "$ROOT/build/DerivedData" \
  PRODUCT_BUNDLE_IDENTIFIER=local.compositor.zhcn \
  INFOPLIST_KEY_CFBundleDisplayName='Compositor 中文版' \
  CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
  DEVELOPMENT_TEAM= build 2>&1 | tee "$ROOT/build/logs/release.log"
APP="$ROOT/build/DerivedData/Build/Products/Release/Compositor.app"
test -d "$APP"
ditto "$APP" "$ROOT/build/products/Compositor-zh-CN.app"
codesign --verify --deep --strict "$ROOT/build/products/Compositor-zh-CN.app"
echo "已构建并验证本地签名：$ROOT/build/products/Compositor-zh-CN.app"
echo '本地签名不等于 Apple 公证；此脚本不会安装应用或修改 Gatekeeper。'
