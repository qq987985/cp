#!/usr/bin/env python3
"""Create and verify a drag-to-Applications DMG using macOS system tools."""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from verify_bundle import verify

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(app):
    result = {}
    for path in sorted(app.rglob("*")):
        key = str(path.relative_to(app))
        if path.is_symlink():
            result[key] = ["symlink", os.readlink(path)]
        elif path.is_file():
            result[key] = ["file", stat.S_IMODE(path.stat().st_mode), sha256(path)]
        elif path.is_dir():
            result[key] = ["directory"]
        else:
            raise ValueError("App 含不支持的特殊文件：" + key)
    return result


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise ValueError(str(args[0]) + " 失败：" + result.stderr.strip() + "\n" + result.stdout.strip())
    return result.stdout


def detach_owned_image(image, mount):
    def owned_images():
        info = plistlib.loads(run("/usr/bin/hdiutil", "info", "-plist").encode("utf-8"))
        return [entry for entry in info.get("images", [])
                if entry.get("image-path") and Path(entry["image-path"]).resolve() == image.resolve()]

    images = owned_images()
    if len(images) > 1:
        raise ValueError("临时安装盘有多个挂载记录，保留目录等待处理")
    device = next((entry.get("dev-entry") for entry in images[0].get("system-entities", [])
                   if entry.get("dev-entry")), None) if images else None
    if device or os.path.ismount(mount):
        run("/usr/bin/hdiutil", "detach", device or mount)
    if os.path.ismount(mount) or owned_images():
        raise ValueError("未能确认临时安装盘已卸载")


def package(app, output, report):
    if platform.system() != "Darwin":
        raise ValueError("DMG 打包需要 macOS")
    app = app.resolve(strict=True)
    output = output.resolve()
    if app.suffix != ".app" or not app.is_dir():
        raise ValueError("输入必须是已构建的 .app")
    if output.suffix != ".dmg" or output.exists() or output.is_relative_to(app):
        raise ValueError("输出必须是尚不存在且位于 App 外的 .dmg")
    source_check = {"status": "FAIL", "checks": [], "commands": []}
    verify(app, "local.compositor.zhcn", source_check)
    original = manifest(app)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".compositor-dmg-", dir=output.parent))
    mount = temporary / "mounted"
    attachment_attempted = False
    try:
        stage = temporary / "stage"
        stage.mkdir()
        run("/usr/bin/ditto", app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        if manifest(stage / app.name) != original:
            raise ValueError("暂存 App 与输入内容不一致")
        image = temporary / "installer.dmg"
        run("/usr/bin/hdiutil", "create", "-fs", "HFS+", "-volname", "Compositor 中文版",
            "-srcfolder", stage, "-format", "UDZO", image)
        run("/usr/bin/hdiutil", "verify", image)
        mount.mkdir()
        attachment_attempted = True
        run("/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
            "-mountpoint", mount, image)
        mounted_app = mount / app.name
        link = mount / "Applications"
        if not link.is_symlink() or os.readlink(link) != "/Applications":
            raise ValueError("安装盘缺少正确的 Applications 拖放目标")
        if manifest(mounted_app) != original or manifest(app) != original:
            raise ValueError("安装盘内的 App 或输入 App 内容发生变化")
        bundle_check = {"status": "FAIL", "checks": [], "commands": []}
        verify(mounted_app, "local.compositor.zhcn", bundle_check)
        report["bundleVerification"] = bundle_check
        detach_owned_image(image, mount)
        # Refuse an existing destination rather than silently replacing an installer.
        if output.exists():
            raise ValueError("输出文件已存在，拒绝覆盖")
        image.rename(output)
        report.update(status="PASS", dmgPath=str(output), dmgSha256=sha256(output),
                      sourceApp=str(app), appFileCount=len(original),
                      checks=["hdiutil verify 通过", "只读挂载通过", "Applications 拖放链接有效",
                              "盘内 App 与输入文件及执行权限一致", "盘内 App 中文资源、框架链接和严格签名通过"],
                      notarization="NOT PERFORMED", uiReview="Unchanged app; no new UI acceptance")
    finally:
        if attachment_attempted:
            try:
                # Also covers an attach command that mounted the image before failing or timing out.
                detach_owned_image(image, mount)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                report["temporaryDirectory"] = str(temporary)
                raise ValueError("无法确认卸载；保留临时目录以避免删除挂载内容：" + str(temporary)) from error
        shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, default=ROOT / "build/logs/dmg-verification.json")
    args = parser.parse_args()
    report = {"status": "FAIL"}
    try:
        package(args.app, args.output, report)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.update(status="FAIL", error=str(error))
        print("DMG 打包失败：" + str(error), file=sys.stderr)
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        return 1
    print("DMG 已生成并验证：" + report["dmgPath"])
    print("SHA-256：" + report["dmgSha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
