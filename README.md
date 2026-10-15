# Compositor-zh-CN

基于 [robbietilton/Compositor](https://github.com/robbietilton/Compositor) 的独立简体中文个人版工程。GitHub 仓库：[qq987985/cp](https://github.com/qq987985/cp)。保留英文源码快照，只对构建副本的显示边界添加翻译，不修改工程格式或枚举内部值。

**状态：已通过 GitHub Actions 的 Xcode Release 构建、App 打包与签名校验；实际界面尚未验收。** 当前识别的静态显示文本均有译文；动态文本、系统菜单、排版仍需运行 App 核验，详细结果见 `reports/`。请勿把静态覆盖率当作完整汉化率。

## 快速使用

需要 macOS 26+、Apple Silicon、Python 3；编译还需要完整 Xcode 26+（Command Line Tools 不足）。脚本仅使用 Python 标准库，不自动安装工具。

```bash
git clone https://github.com/qq987985/cp.git Compositor-zh-CN
cd Compositor-zh-CN
python3 scripts/localize.py prepare
python3 scripts/verify.py
bash scripts/build.sh
bash scripts/run.sh
```

也可双击 `一键准备.command`，生成可在 Xcode 打开的 `build/source/Compositor.xcodeproj`，选择 Compositor scheme。**推荐使用构建脚本**，其产物为 `build/products/Compositor-zh-CN.app`。它使用独立 bundle ID `local.compositor.zhcn`，不会覆盖已安装的原版。脚本不会安装 App、关闭系统安全机制或申请公证。需要本地确认允许打开时按 macOS 正常流程处理。

英文备用启动：`bash scripts/run.sh en`；中文：`bash scripts/run.sh zh`。先退出当前 App，再切换语言。原版 Sparkle 二进制更新已在构建副本禁用，避免中文版本被英文官方版本覆盖；源码更新请使用下述流程。

## 目录

| 路径 | 用途 |
|---|---|
| `vendor/Compositor/` | 未修改的官方完整源码快照，包含原版 README、MIT 许可和测试 |
| `UPSTREAM_COMMIT` | 快照对应的精确 Git 提交 |
| `scripts/localize.py` | 拉取、提取、显示边界补丁、翻译、导入和漏翻报告 |
| `scripts/CN.swift` | 显示文本翻译，支持编号占位符与英文回退 |
| `translations/zh-CN.json` | 人工中文译文，优先级最高；直接编辑此文件 |
| `translations/glossary.tsv` | 初始术语参考；修改不会自动覆盖 JSON |
| `translations/inventory.json` | 所有候选字符串、文件和行号；也包含不应翻译的代码标识 |
| `translations/machine.zh-CN.json` | 可选在线翻译缓存；不含 API 密钥 |
| `patches/anchors.json` | 手工审计的动态文字和兼容补丁，锚点变化时停止 |
| `patches/generated.patch` | 当前 Swift 显示边界的可审核差异，prepare 自动生成 |
| `build/source/` | 可丢弃、可重新生成的中文构建副本 |
| `build/products/`、`build/logs/` | App 产物和构建日志 |
| `reports/` | 漏翻、动态待审、覆盖统计和验证状态 |

**不要把自己的修改只放在 `build/source/`**：每次 prepare/build 会重建此目录。请将译文放在 translations，将额外源码修改放在 patches。`vendor/` 保持原样。

## 拉取新版与复现

初次使用无需联网拉取，已包含固定快照。需要更新时：

```bash
python3 scripts/localize.py fetch --ref origin/main
python3 scripts/localize.py prepare
python3 scripts/verify.py
```

fetch 先下载到 `build/fetch/`，成功后将旧 vendor 重命名备份，再写入新快照和提交号。重复拉取前须移动已有 `build/fetch/`，防止误覆盖。也可用 `--ref <完整提交号>` 固定版本。上游变化导致补丁锚点不匹配时脚本停止，需审核新源码与 `patches/anchors.json`，不会静默跳过补丁。首次编译 Sparkle 等 Xcode 包依赖需要网络。

## 提取、翻译和导入

`prepare` 使用 Swift 字符串/注释扫描器提取候选，添加显示边界调用并写入翻译资源。无需在线翻译即可使用内置中文词典。翻译入口为 JSON；机器译文缓存低于人工词典。

可选调用你指定的 OpenAI-compatible Chat Completions 翻译服务（可能由服务商计费）。默认只发送识别出的 UI 静态文本，不发送仓库、图片或用户工程。没有预设服务，也不会使用 GitHub 令牌作为翻译密钥。

```bash
read -rs COMPOSITOR_TRANSLATE_API_KEY
export COMPOSITOR_TRANSLATE_API_KEY
# 输入自己的服务完整 HTTPS 地址和模型名：
python3 scripts/localize.py translate --url https://YOUR-SERVICE/v1/chat/completions --model YOUR-MODEL
unset COMPOSITOR_TRANSLATE_API_KEY
```

每批成功后立即保存缓存；中断后重复执行可续跑。校验每个 `{0}`、`{1}` 占位符，响应缺失或变更占位符则停止。人工词典永远优先。默认只补未翻译的 UI 文本；`--all` 会发送全量候选（含内部标识），仅适合人工审查，**并不意味着会修改这些内部标识**。动态显示词条也可直接在 JSON 补译。

```bash
python3 scripts/localize.py import   # 修改译文后刷新 build/source 资源
python3 scripts/localize.py report   # 刷新报告
```

生成的 `Localizable.xcstrings` 保留英文源语言和 zh-Hans 译文；运行时字典额外处理 SwiftUI 的动态 String、AppKit 文本及插值。标准 Xcode 导出/导入可用：

```bash
bash scripts/xcode-localizations.sh export
bash scripts/xcode-localizations.sh import /绝对路径/zh-Hans.xcloc
```

Xcode 原生导出不保证发现所有动态文字；以项目 inventory 和显示边界报告补充。Xcode 导入只改临时副本，持久译文请同步到 JSON。此辅助流程未在本机执行过（缺少完整 Xcode）。

## 漏翻与验收

- `untranslated-ui.json`：已识别的静态显示文字中缺少译文的项。
- `untranslated.json`：全量候选缺译文，含内部键、日志、着色器名和文件名，不能全部直接汉化。
- `dynamic-review.json`：动态表达式、数字、用户数据及需人工分类的位置。部分已由锚点补丁处理，仍保留为审计清单。
- `display-sites.json`：脚本识别的显示边界，包括动态控件标签。
- `summary.json`、`VERIFICATION.md`：统计和已验证/未验证的范围。

App 中依次验收：菜单栏、画笔与选区工具、图层右键、全部混合模式及预览、滤镜/Camera Raw、画布和网格设置、快捷键中文搜索与重映射、错误弹窗、工程保存重开、英文备用语言。还需检查长译文是否截断、窗口缩小是否挤压控件。用户自定义图层名、工程名、字体名、文件路径保持不变。参见 `docs/验收清单.md`。

## GitHub 构建

Actions 中 `Verify` 会检查准备流程与回归测试；`Build Chinese App` 需手动点击 Run workflow，使用 macOS 26 / Xcode 构建。成功后下载 `Compositor-zh-CN-app` artifact，解压内层 ZIP 得到 App。本次成功构建记录见 reports/cloud-build.md；后续是否成功以对应运行日志为准。

## 来源与限制

当前基线见 `UPSTREAM_COMMIT`，项目创建时从官方 main 拉取。此前聊天中的 `/mnt/data/Compositor-中文自动汉化工具.zip` 在当前文件系统不存在，无法读取或验证；本项目为重新制作，未声称迁移该 ZIP 内容。

上游 MIT 许可保存在 `LICENSE.upstream` 和 vendor 内；本项目脚本也按 MIT 许可。官方目前不接收翻译 PR，维护此独立项目不向上游提交汉化。上游资料：[构建与要求](https://github.com/robbietilton/Compositor#requirements)、[Apple String Catalog](https://developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog)、[GitHub macOS runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
