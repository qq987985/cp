> 更正：早期验证遗漏实际启动测试，build 49 在用户机器上出现 DYLD/Sparkle 加载崩溃。下面为历史记录；build 50 新增的实际启动验证见 startup-fix.md。

# 验证记录

日期：2026-10-16。基线提交见 UPSTREAM_COMMIT，原版快照逐文件摘要见 upstream-sha256.json。

已通过：
- 157 个 Swift 文件语法解析（不等同于 App 类型检查或构建）。
- CN.swift 单独类型检查，使用本机 Swift 6.4。
- 6 项 Swift 翻译运行时检查：Bundle 资源加载、静态译文、编号插值、用户内容占位符保护、英文备用模式等。
- 9 项 Python 回归检查：枚举声明、工程 manifest、混合模式标识、注释/插值扫描、静态显示词条覆盖等。
- 712 个已识别静态显示 key 均有译文；共识别 1095 处显示边界。

待验证：
- 89 项动态表达式审计清单（含数字、用户数据，以及已被锚点补丁覆盖的项）。
- App 编译、启动、实际中文界面、排版和完整功能回归。
- Xcode 原生导出/导入与上游 App 单元测试。

本机仅安装 Command Line Tools，Release 脚本检测后以状态 2 停止。GitHub Actions 结果以运行页面为准。旧聊天 ZIP 当前不存在，未迁移。没有调用在线翻译服务。

静态显示缺译文为零不代表完整汉化率为 100%。全量未译候选仍包含内部标识、日志等，需要分类审查，不能全部替换。

## 云端构建补充

后续已由 GitHub Actions 成功执行完整 Xcode Release 构建、打包和本地签名验证。本机再次验证下载 App 的签名、独立 bundle ID、中文 lproj 和 JSON 资源均通过。源码提交及成功日志见 [cloud-build.md](cloud-build.md)。上文“本机缺少 Xcode”仍然成立；App 实际界面及完整功能仍未验收。
