# build 50 启动崩溃修复

用户提供的 build 49 报告指出：DYLD 加载 Sparkle.framework 时拒绝其签名，程序尚未进入主界面便退出。静态 codesign 校验通过不能证明实际动态库加载成功。

修复：仅修改自动生成的个人版，移除已停用的 Sparkle 更新器代码、import、Xcode 链接/包引用、Package.resolved、官方更新配置和 helper mach-lookup 权限例外；vendor 原始快照保持不变。保留 Hardened Runtime 与 App Sandbox，不新增 disable-library-validation 权限。App build 号改为 50。

本地检查：10 项回归测试通过；156 个 Swift 文件语法解析通过；Xcode 项目、Info.plist 和 entitlements 结构校验通过；prepare 重复执行结果一致；vendor 摘要未变化。

云端：待执行完整 clean Release 构建和最终 ZIP 解压副本的启动验证。

完整汉化和编辑功能验收不在本次启动检查的已验证范围内。
