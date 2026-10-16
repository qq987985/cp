#!/usr/bin/env python3
"""GitHub-only upgrade pipeline; no translation API, external packages or user files."""
import argparse
import datetime
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "robbietilton/Compositor"
STATE = ROOT / "build/upgrade-plan.json"
RELEASE_DIR = ROOT / "build/release"
GENERATED = [
    "vendor/Compositor", "UPSTREAM_COMMIT", "translations/inventory.json", "patches/generated.patch",
    "reports/display-sites.json", "reports/dynamic-review.json", "reports/untranslated.json",
    "reports/untranslated-ui.json", "reports/summary.json", "reports/upstream-sha256.json", "reports/upstream-compat.json",
]


def run(*args, capture=False):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        detail = (result.stderr or "").strip() if capture else "详见前面的步骤日志"
        raise ValueError(str(args[0]) + " 执行失败：" + detail)
    return result.stdout.strip() if capture else ""


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_ref(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value):
        raise ValueError("upstream_ref 仅允许 main、标签或 SHA 中的字母、数字、点、横线、下划线和斜线")
    if ".." in value or "//" in value or value.endswith(("/", ".")) or any(
            part.startswith(".") or part.endswith(".lock") for part in value.split("/")):
        raise ValueError("upstream_ref 含不安全的 Git ref 片段")
    return value


def context():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("此发布脚本只能由 GitHub Actions 在 main 分支运行；请使用 Upgrade and release Chinese App")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY 无效")
    if run("git", "branch", "--show-current", capture=True) != "main":
        raise ValueError("必须检出 main 分支")
    origin = run("git", "remote", "get-url", "origin", capture=True).removesuffix(".git")
    if origin != "https://github.com/" + repository:
        raise ValueError("origin 与当前 GitHub 仓库不匹配")
    return repository


def api(route):
    return json.loads(run("gh", "api", route, capture=True))


def releases(repository):
    pages = json.loads(run("gh", "api", "--paginate", "--slurp",
                          "repos/" + repository + "/releases?per_page=100", capture=True))
    return [release for page in pages for release in page]


def output(key, value):
    if "\n" in value or "\r" in value:
        raise ValueError("无效 workflow output")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(key + "=" + value + "\n")


def summary(message):
    print(message, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(message + "\n\n")


def prepare():
    repository = context()
    if run("git", "status", "--porcelain", capture=True):
        raise ValueError("升级前工作区必须干净")
    requested = validate_ref(os.environ.get("UPSTREAM_REF", "main"))
    resolved = requested
    if requested == "latest":
        resolved = validate_ref(api("repos/" + UPSTREAM + "/releases/latest")["tag_name"])
    upstream_sha = api("repos/" + UPSTREAM + "/commits/" + quote(resolved, safe=""))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_sha):
        raise ValueError("官方 API 未返回完整上游 commit SHA")
    all_releases = releases(repository)
    record_path = ROOT / "reports/upgrades" / (upstream_sha + ".json")
    known_tag = load(record_path).get("release_tag") if record_path.exists() else None
    matching = [r for r in all_releases if r.get("tag_name") == known_tag or re.search(
        r"(?<![0-9a-f])" + upstream_sha + r"(?![0-9a-f])", r.get("body") or "")]
    if any(r.get("draft") for r in matching):
        raise ValueError("同一上游版本存在未完成的 Release 草稿；为避免覆盖，请先在 GitHub 检查该草稿")
    published = next((r for r in matching if not r.get("draft")), None)
    if published:
        output("skip", "true")
        summary("无需升级：同一上游 commit 已发布，未改动源码或覆盖资产。\n" + published["html_url"])
        return
    if known_tag:
        raise ValueError("此上游已有已验证记录，但对应 Release 缺失；请检查上次运行与 tag " + known_tag + "，不会覆盖重建")
    previous_sha = (ROOT / "UPSTREAM_COMMIT").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", previous_sha):
        raise ValueError("当前 UPSTREAM_COMMIT 不是完整 SHA，拒绝升级")
    if upstream_sha == previous_sha:
        output("skip", "true")
        summary("无需升级：目标与当前锁定的上游 commit 相同，未改动源码或创建重复版本。")
        return
    ancestry = ROOT / "build/upstream-ancestry.git"
    if ancestry.exists():
        raise ValueError("上游祖先检查目录已存在，请使用新的 GitHub Actions 运行")
    run("git", "clone", "--bare", "--filter=blob:none", "https://github.com/" + UPSTREAM + ".git", ancestry)
    run("git", "-C", ancestry, "fetch", "origin", previous_sha, upstream_sha)
    check = subprocess.run(["git", "-C", str(ancestry), "merge-base", "--is-ancestor", previous_sha, upstream_sha], cwd=ROOT)
    if check.returncode == 1:
        output("skip", "true")
        summary("未升级：所选上游 ref `" + resolved + "` 落后于当前锁定版本或不在其后继历史中。"
                + "为避免降级，保持现有版本；可改选 main。")
        return
    if check.returncode:
        raise ValueError("无法验证上游提交祖先关系，拒绝升级")
    if STATE.exists() or (ROOT / "build/fetch").exists():
        raise ValueError("升级工作目录已存在；请使用新的 GitHub Actions 运行")
    base = run("git", "rev-parse", "HEAD", capture=True)
    run(sys.executable, ROOT / "scripts/localize.py", "fetch", "--ref", upstream_sha)
    if (ROOT / "UPSTREAM_COMMIT").read_text().strip() != upstream_sha:
        raise ValueError("拉取后的上游 commit 不匹配")
    run(sys.executable, ROOT / "scripts/localize.py", "prepare")
    run(sys.executable, ROOT / "scripts/verify.py", "--allow-untranslated")
    save(STATE, {"repository": repository, "base_commit": base, "upstream_sha": upstream_sha,
                 "requested_ref": requested, "resolved_ref": resolved, "verified": False})
    output("skip", "false")
    summary("已拉取官方 commit `" + upstream_sha + "` 并复用已有中文词典。新增缺译文本使用英文；未调用在线翻译。")


def checked_state():
    repository = context()
    state = load(STATE)
    if state.get("repository") != repository or (ROOT / "UPSTREAM_COMMIT").read_text().strip() != state.get("upstream_sha"):
        raise ValueError("升级状态与当前仓库或上游锁定版本不匹配")
    if run("git", "rev-parse", "HEAD", capture=True) != state.get("base_commit"):
        raise ValueError("升级过程中 HEAD 已改变")
    return state


def verify():
    state = checked_state()
    app = ROOT / "build/products/Compositor-zh-CN.app"
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    version = info.get("CFBundleShortVersionString", "")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9.-]+)?", version):
        raise ValueError("App MARKETING_VERSION 无效，拒绝生成 Release tag")
    tag = "zh-cn-" + version + "-" + state["upstream_sha"][:7]
    if any(r.get("tag_name") == tag for r in releases(state["repository"])):
        raise ValueError("Release tag 已存在，拒绝覆盖：" + tag)
    existing_tag = run("git", "ls-remote", "--tags", "origin", "refs/tags/" + tag, capture=True)
    if existing_tag:
        raise ValueError("远端 tag 已存在，拒绝覆盖：" + tag)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    app_zip = RELEASE_DIR / ("Compositor-zh-CN-" + version + "-" + state["upstream_sha"][:7] + "-app.zip")
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, app_zip)
    extracted = ROOT / "build/upgrade-package-check"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    run("ditto", "-x", "-k", app_zip, extracted)
    run(sys.executable, ROOT / "scripts/verify_bundle.py", extracted / app.name)
    run(sys.executable, ROOT / "scripts/smoke_launch.py", extracted / app.name, "--seconds", "12")
    bundle_check = load(ROOT / "build/logs/bundle-verification.json")
    smoke = load(ROOT / "build/logs/smoke-launch.json")
    if bundle_check.get("status") != "PASS" or smoke.get("status") != "PASS" or smoke.get("observed_seconds", 0) < 10:
        raise ValueError("最终 ZIP 的签名/资源或启动报告未通过")
    app_dmg = app_zip.with_suffix(".dmg")
    dmg_report_path = ROOT / "build/logs/upgrade-dmg.json"
    run(sys.executable, ROOT / "scripts/package_dmg.py", extracted / app.name, app_dmg,
        "--report", dmg_report_path)
    dmg_report = load(dmg_report_path)
    if (dmg_report.get("status") != "PASS"
            or Path(dmg_report.get("dmgPath", "")).resolve() != app_dmg.resolve()
            or dmg_report.get("dmgSha256") != sha256(app_dmg)):
        raise ValueError("最终 DMG 的完整性验证报告或 SHA-256 不匹配")
    missing = load(ROOT / "reports/untranslated-ui.json")
    report = load(ROOT / "reports/summary.json")
    report.update(xcode_build="VERIFIED: clean Release build; packaged bundle verified",
                  ui_review="NOT VERIFIED: launch only; windows, editing and all text not inspected",
                  missing_literal_ui_keys=len(missing),
                  launch_smoke={"status": "PASS", "observed_seconds": smoke["observed_seconds"]})
    save(ROOT / "reports/summary.json", report)
    record = {
        "schema": 1, "upstream_repository": UPSTREAM, "upstream_commit": state["upstream_sha"],
        "requested_ref": state["requested_ref"], "resolved_ref": state["resolved_ref"], "release_tag": tag,
        "marketing_version": version, "build_version": str(info.get("CFBundleVersion", "")),
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "workflow_run": "https://github.com/" + state["repository"] + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", ""),
        "app_zip_sha256": sha256(app_zip), "app_dmg_sha256": dmg_report["dmgSha256"],
        "bundle_checks": bundle_check["checks"],
        "dmg_package": {"status": "PASS", "asset": app_dmg.name},
        "launch_smoke_seconds": smoke["observed_seconds"], "missing_literal_ui_keys": len(missing),
        "ui_review": "NOT VERIFIED: startup/process only; no window or editing acceptance",
        "translation_policy": "Existing dictionary reused; untranslated new text falls back to English; no online translation",
    }
    record_relative = "reports/upgrades/" + state["upstream_sha"] + ".json"
    save(ROOT / record_relative, record)
    state.update(verified=True, release_tag=tag, version=version, app_zip=str(app_zip.relative_to(ROOT)),
                 app_zip_sha256=record["app_zip_sha256"], app_dmg=str(app_dmg.relative_to(ROOT)),
                 app_dmg_sha256=record["app_dmg_sha256"], record_path=record_relative, missing_ui=len(missing))
    save(STATE, state)
    summary("最终 App ZIP 已通过签名、无 Sparkle、中文资源检查和至少 12 秒启动检查；DMG 已生成并通过完整性验证。"
            + "未进行窗口、排版或编辑功能验收。缺译静态 UI："
            + str(len(missing)) + " 项，使用英文回退。")


def publish():
    state = checked_state()
    if state.get("verified") is not True:
        raise ValueError("未完成最终 ZIP 和 DMG 验证，拒绝提交或发布")
    app_zip = ROOT / state["app_zip"]
    if sha256(app_zip) != state["app_zip_sha256"]:
        raise ValueError("App ZIP 在启动验证后发生变化，拒绝发布")
    app_dmg = ROOT / state["app_dmg"]
    if sha256(app_dmg) != state["app_dmg_sha256"]:
        raise ValueError("DMG 在完整性验证后发生变化，拒绝发布")
    # Only these official snapshot/generated paths can enter the commit or source archive.
    allowed = GENERATED + [state["record_path"]]
    changed = run("git", "diff", "--name-only", "HEAD", capture=True).splitlines()
    untracked = run("git", "ls-files", "--others", "--exclude-standard", capture=True).splitlines()
    for path in changed + untracked:
        if not any(path == entry or path.startswith(entry + "/") for entry in allowed):
            raise ValueError("出现升级范围外的文件，拒绝自动提交：" + path)
    run("git", "fetch", "origin", "main")
    if run("git", "rev-parse", "origin/main", capture=True) != state["base_commit"]:
        raise ValueError("main 在构建期间已有新提交；请重新运行，脚本不会覆盖或强制推送")
    if any(r.get("tag_name") == state["release_tag"] for r in releases(state["repository"])):
        raise ValueError("发布版本已存在，拒绝覆盖")
    if run("git", "ls-remote", "--tags", "origin", "refs/tags/" + state["release_tag"], capture=True):
        raise ValueError("发布 tag 已存在，拒绝覆盖")
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", "-A", "--", *allowed)
    run("git", "commit", "-m", "Upgrade Compositor Chinese build to " + state["version"] + " (" + state["upstream_sha"][:7] + ")")
    commit = run("git", "rev-parse", "HEAD", capture=True)
    source_zip = RELEASE_DIR / ("Compositor-zh-CN-" + state["version"] + "-" + state["upstream_sha"][:7] + "-source.zip")
    run("git", "archive", "--format=zip", "--prefix=Compositor-zh-CN/", "--output=" + str(source_zip), commit)
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError("可编辑源码 ZIP 完整性检查失败")
        for required in ["README.md", "scripts/localize.py", "scripts/package_dmg.py",
                         "translations/zh-CN.json", "UPSTREAM_COMMIT"]:
            if "Compositor-zh-CN/" + required not in archive.namelist():
                raise ValueError("可编辑源码 ZIP 缺少：" + required)
    sums = RELEASE_DIR / "SHA256SUMS.txt"
    sums.write_text("".join(sha256(path) + "  " + path.name + "\n" for path in [app_dmg, app_zip, source_zip]), encoding="utf-8")
    notes = RELEASE_DIR / "release-notes.md"
    notes.write_text(
        "下载 `" + app_dmg.name + "`，双击打开，将 `Compositor-zh-CN.app` 拖到“应用程序（Applications）”文件夹，"
        + "然后从“应用程序”启动。App ZIP 是备用下载，可解压后使用。\n\n"
        + "基于官方源码的简体中文个人版，适用于 Apple Silicon Mac。\n\n"
        + "Upstream commit: " + state["upstream_sha"] + "\n\n"
        + "官方来源：https://github.com/" + UPSTREAM + "/commit/" + state["upstream_sha"] + "\n\n"
        + "项目源码 commit: " + commit + "\n\n"
        + "已验证 clean Release 构建；最终 ZIP 解压后的独立 Bundle ID、中文资源、无 Sparkle 链接和本地签名；"
        + "在 macOS GUI 会话中运行至少 12 秒，AppKit 确认完成启动。DMG 由同一份已验证 App 制作，并通过磁盘映像完整性验证。\n\n"
        + "保留已有词典。本次识别的静态 UI 缺译 " + str(state["missing_ui"]) + " 项，新增缺译文本使用英文回退。"
        + "未调用在线翻译，未验收全部窗口、动态文本、排版或图像编辑功能。\n\n"
        + "App 使用本地 ad-hoc 签名，未进行 Apple 公证。可编辑完整项目见 source ZIP；"
        + "DMG、App ZIP 和源码 ZIP 的 SHA-256 见 SHA256SUMS.txt。\n", encoding="utf-8")
    run("git", "tag", "-a", state["release_tag"], "-m", "Verified Chinese build; upstream " + state["upstream_sha"])
    publication = {"status": "PENDING", "source_commit": commit, "release_tag": state["release_tag"],
                   "upstream_commit": state["upstream_sha"],
                   "assets": {path.name: sha256(path) for path in [app_dmg, app_zip, source_zip, sums]}}
    save(ROOT / "build/logs/upgrade-publication.json", publication)
    # Atomic push prevents a tag/main mismatch; never force-push either reference.
    run("git", "push", "--atomic", "origin", "HEAD:refs/heads/main", "refs/tags/" + state["release_tag"])
    # Keep a failed upload private as a draft. A rerun refuses to overwrite an existing draft/version.
    run("gh", "release", "create", state["release_tag"], str(app_dmg), str(app_zip), str(source_zip), str(sums),
        "--repo", state["repository"], "--verify-tag", "--draft", "--title", "Compositor 中文版 " + state["version"],
        "--notes-file", notes)
    run("gh", "release", "edit", state["release_tag"], "--repo", state["repository"], "--draft=false", "--latest")
    publication["status"] = "PUBLISHED"
    save(ROOT / "build/logs/upgrade-publication.json", publication)
    summary("已发布：https://github.com/" + state["repository"] + "/releases/tag/" + state["release_tag"]
            + "\nDMG 安装包、备用 App ZIP、可编辑源码与 SHA256SUMS.txt 已上传；未上传用户文件或凭证。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "verify", "publish"])
    args = parser.parse_args()
    try:
        {"prepare": prepare, "verify": verify, "publish": publish}[args.phase]()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, plistlib.InvalidFileException) as error:
        save(ROOT / ("build/logs/upgrade-" + args.phase + "-error.json"),
             {"status": "FAIL", "phase": args.phase, "error": str(error)})
        print("升级已停止：" + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
