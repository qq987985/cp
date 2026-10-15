# Compositor-zh-CN 维护约定

默认中文沟通。vendor/Compositor 是未修改的上游快照，不直接改它。构建副本在 build/source，每次 prepare 重建。修改译文用 translations/zh-CN.json，修改显示边界逻辑用 scripts/localize.py，精确源码修补用 patches/anchors.json。禁止翻译持久化 rawValue、工程格式标识、快捷键 id、文件路径及用户命名。

完成修改后运行 python3 scripts/localize.py prepare 和 python3 scripts/verify.py；有 Swift 时执行语法解析；有完整 Xcode 才运行 bash scripts/build.sh。没有成功构建日志时不宣称编译成功。App 中检查中文显示、混合模式选择和快捷键后才能声明 UI 验收。不要在脚本、日志或仓库中保存访问令牌。
