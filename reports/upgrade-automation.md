# GitHub 一键升级

入口：[Upgrade and release Chinese App](https://github.com/qq987985/cp/actions/workflows/upgrade.yml)。选择 main 分支，输入默认 main，点击 Run workflow。无定时任务，只有手动运行才检查。

已实现：官方完整SHA锁定、禁止回退、重复发布跳过、中文词典复用、新词条英文回退及数量披露、结构化移除闲置更新依赖、构建号从官方基线加一、clean Release、最终ZIP解压后实际启动检查、通过后才提交快照并发布App/源码/SHA-256。

本地验证：13项回归检查通过。模拟构建号/依赖版本变化可处理；无关依赖、服务权限和语言保留；未知更新器代码会在修改前停止。当前基线生成的156个Swift文件与已验证build50逐字节相同，Info.plist/entitlements内容相同，Xcode结构只调整knownRegions的顺序（保留相同语言集合）。

云端试运行：待执行当前main无新版检查。真正的新上游版本将由每次升级的构建和启动检查决定是否发布，本记录不宣称未来版本已验证。
