# build 50 启动崩溃修复

用户提供的 build 49 报告指出：DYLD 加载 Sparkle.framework 时拒绝其签名，程序尚未进入主界面便退出。静态 codesign 校验通过不能证明实际动态库加载成功。

修复：仅修改自动生成的个人版，移除已停用的 Sparkle 更新器代码、import、Xcode 链接/包引用、Package.resolved、官方更新配置和 helper mach-lookup 权限例外；vendor 原始快照保持不变。保留 Hardened Runtime 与 App Sandbox，不新增 disable-library-validation 权限。App build 号改为 50。

本地检查：10 项回归测试通过；156 个 Swift 文件语法解析通过；Xcode 项目、Info.plist 和 entitlements 结构校验通过；prepare 重复执行结果一致；vendor 摘要未变化。

云端：已通过完整 clean Release 构建、最终 ZIP 解压副本验证和 12.1 秒的启动检查。[成功运行 #38826018326](https://github.com/qq987985/cp/actions/runs/38826018326)，源码提交 ac983d1。详细记录见 build50-cloud-* 文件。

本机：下载同一份 ZIP 后，确认版本 1.5.3 (50)、无 Sparkle 链接/框架、独立 Bundle ID 和中文资源、严格签名均通过；持续启动 30.1 秒，AppKit 确认完成启动。通过 Computer Use 实际看到“未命名”主窗口、新建画布、中文工具栏与图层面板；仍存在部分英文菜单/提示，未宣称完整汉化。测试完成后只关闭本次测试进程。详细记录见 build50-local-* 文件。

完整汉化和编辑功能验收不在本次启动检查的已验证范围内。

签名兼容背景可参考 [Apple Code Signing Guide：Using Library Validation](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)。本次修复删除闲置依赖，未关闭系统库验证。
