> 历史记录：此 build 49 虽通过编译和静态签名检查，后来已确认启动时存在 Sparkle 加载签名冲突。请勿再下载此历史产物。build 50 修复记录见 [startup-fix.md](startup-fix.md)。

# 云端 Release 构建记录

日期：2026-10-16（北京时间）。

**成功构建源码提交：886f95bf2dbb13569ee35299b2fe631bc1b46e91**

运行：[Build Chinese App #38825083918](https://github.com/qq987985/cp/actions/runs/38825083918)。GitHub macOS 26 arm64 runner，Xcode 具体版本见 cloud-xcode-version.txt。构建、打包和上传产物步骤全部成功，详细编译输出见 cloud-release.log。

下载运行页面中的 `Compositor-zh-CN-app` artifact，解压内层 ZIP 得到 App。本次 App 使用本地 ad-hoc 签名，未做 Apple 开发者公证。

下载到本机后再次通过 `codesign --verify --deep --strict`，并确认：
- bundle ID 为 local.compositor.zhcn。
- 包含 zh-Hans.lproj 中文资源。
- 包含 1756 条运行时字典记录（包含原文保留项、省略号变体；不是界面文案数量）。
- 保存菜单的运行时译文为“保存”。

第一轮构建发现 String Catalog 自动生成符号时的重名冲突，已通过关闭 STRING_CATALOG_GENERATE_SYMBOLS 修复，并由本次完整构建验证。

**本记录不代表 App 界面、动态漏翻和图像编辑功能已验收。** 本机没有完整 Xcode，编译由 GitHub 云端完成；未在本机启动 App。后续只修改文档和验证记录的提交不改变已验证构建源码。
