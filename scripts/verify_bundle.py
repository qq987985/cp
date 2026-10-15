#!/usr/bin/env python3
"""Validate the actual distributable bundle, using only macOS system tools."""
import argparse
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def bundle_info(app):
    app = Path(app).resolve(strict=True)
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    name = info.get("CFBundleExecutable")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("CFBundleExecutable 无效")
    executable = (app / "Contents/MacOS" / name).resolve(strict=True)
    if app not in executable.parents or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("主可执行文件缺失、不可执行或位于 App 外")
    return app, info, executable


def verify(app, expected_bundle_id, report):
    if platform.system() != "Darwin":
        raise ValueError("完整 App 验证需要 macOS")
    app, info, executable = bundle_info(app)
    report.update(app=str(app), executable=str(executable), bundle_id=info.get("CFBundleIdentifier"))
    if info.get("CFBundleIdentifier") != expected_bundle_id:
        raise ValueError("独立 Bundle ID 不匹配：" + str(info.get("CFBundleIdentifier")))
    report["checks"].append("独立 Bundle ID：" + expected_bundle_id)

    resources = app / "Contents/Resources"
    with (resources / "zh-CN.json").open(encoding="utf-8") as stream:
        dictionary = json.load(stream)
    if not isinstance(dictionary, dict) or not dictionary:
        raise ValueError("zh-CN.json 必须是非空翻译字典")
    if any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in dictionary.items()):
        raise ValueError("zh-CN.json 存在无效或空译文")
    for key, value in dictionary.items():
        if sorted(re.findall(r"\{\d+\}", key)) != sorted(re.findall(r"\{\d+\}", value)):
            raise ValueError("翻译占位符不一致：" + key)
    expected = {}
    for path in [ROOT / "translations/machine.zh-CN.json", ROOT / "translations/zh-CN.json"]:
        if path.exists():
            expected.update(json.loads(path.read_text(encoding="utf-8")))
    if not expected or dictionary != expected:
        raise ValueError("App 翻译字典与当前项目合并译文不一致")
    for key in ["Save", "Settings", "Normal", "Keyboard Shortcuts"]:
        if not re.search(r"[\u3400-\u9fff]", dictionary.get(key, "")):
            raise ValueError("关键中文译文缺失：" + key)
    strings = resources / "zh-Hans.lproj/Localizable.strings"
    # Xcode can emit UTF-16 XML or old-style .strings; plutil handles both without modifying the resource.
    result = subprocess.run(["/usr/bin/plutil", "-convert", "json", "-o", "-", str(strings)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("无法读取编译后的中文资源：" + result.stderr.strip() + result.stdout.strip())
    localized = json.loads(result.stdout)
    if not isinstance(localized, dict) or not any(re.search(r"[\u3400-\u9fff]", str(v)) for v in localized.values()):
        raise ValueError("编译后的 zh-Hans Localizable.strings 缺少中文译文")
    report.update(dictionary_entries=len(dictionary), compiled_chinese_entries=len(localized))
    report["checks"].append("中文运行时字典与编译后的 zh-Hans 资源完整")

    # Inspect every Mach-O, including nested helpers. Do not assume only the main executable links frameworks.
    macho_files = set()
    for path in app.rglob("*"):
        if "sparkle" in path.name.casefold():
            raise ValueError("App 内仍包含 Sparkle：" + str(path.relative_to(app)))
        if path.is_symlink() and app not in path.resolve().parents:
            raise ValueError("App 包含指向外部的符号链接：" + str(path.relative_to(app)))
        if path.is_file():
            with path.open("rb") as stream:
                if stream.read(4) in MACHO_MAGIC:
                    macho_files.add(path.resolve())
    if executable not in macho_files:
        raise ValueError("主可执行文件不是 Mach-O")
    for path in sorted(macho_files):
        result = subprocess.run(["/usr/bin/otool", "-L", str(path)], capture_output=True, text=True, timeout=30)
        report["commands"].append({"tool": "otool -L", "file": str(path), "returncode": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise ValueError("无法读取 Mach-O 链接：" + str(path))
        dependencies = "\n".join(line for line in result.stdout.splitlines() if line[:1].isspace())
        if "sparkle" in dependencies.casefold():
            raise ValueError("Mach-O 仍链接 Sparkle：" + str(path.relative_to(app)))
    report["macho_files"] = len(macho_files)
    report["checks"].append("所有 Mach-O 均无 Sparkle 链接，App 内无 Sparkle 框架")
    result = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
                            capture_output=True, text=True, timeout=60)
    report["commands"].append({"tool": "codesign --verify --deep --strict --verbose=2", "returncode": result.returncode,
                               "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise ValueError("App 严格签名验证失败：" + result.stderr.strip())
    report["checks"].append("codesign --verify --deep --strict 通过")
    report["status"] = "PASS"
    report["ui_review"] = "NOT VERIFIED"
    return app, info, executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="待发布的 Compositor-zh-CN.app")
    parser.add_argument("--bundle-id", default="local.compositor.zhcn")
    parser.add_argument("--report", type=Path, default=ROOT / "build/logs/bundle-verification.json")
    args = parser.parse_args()
    report = {"status": "FAIL", "checks": [], "commands": [], "ui_review": "NOT VERIFIED"}
    try:
        verify(args.app, args.bundle_id, report)
    except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException) as error:
        report["error"] = str(error)
        print("App 验证失败：" + str(error), file=sys.stderr)
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        return 1
    for check in report["checks"]:
        print("通过：" + check)
    print("签名验证不等于 Apple 公证；未进行界面验收。报告：" + str(args.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
