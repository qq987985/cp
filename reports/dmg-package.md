# build 50 DMG 安装盘验证

2026-10-16：从 GitHub 已发布的 build 50 App ZIP 制作拖入“应用程序”的 DMG。没有重新编译或改动 App；App 的原始云端构建与启动验证见 [startup-fix.md](startup-fix.md)。

- 输入 App ZIP SHA-256：`b77bee7232d086a423428ab5a6b1f46a8547c1906ce3aea44dd93c8d9db9d0f2`。
- 发布 DMG：`Compositor-zh-CN-build50.dmg`。
- DMG SHA-256：`7a423cfe14aec65c616db9585381b2dd83e92b57957798beb1dbd69e2a093913`。
- `hdiutil verify` 和只读挂载通过；Applications 符号链接指向 `/Applications`。
- 盘内 App 所有文件内容、符号链接及文件权限与输入一致；独立 Bundle ID、中文资源、无 Sparkle 链接、严格签名均通过。
- 已实际测试“挂载成功后报错”：正式 DMG 不生成，本次映像及临时目录安全清理，原有外部映像不变，源 App 的 17 项文件/目录记录不变。已有输出文件会在调用外部工具前拒绝覆盖。
- App 使用原有本地 ad-hoc 签名，DMG 未进行 Apple 公证；本次打包没有新增完整 UI 或编辑功能验收。

`scripts/package_dmg.py` 只修改临时副本；挂载后即使报错，也会按精确映像路径检查并卸载本次映像。无法确认卸载时保留临时目录并停止。GitHub 手动构建与一键上游升级均已接入 DMG 打包和验证。
