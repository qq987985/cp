#!/usr/bin/env python3
"""Launch one app instance in the current macOS GUI session and observe its PID."""
import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from verify_bundle import ROOT, bundle_info

PREFLIGHT_JXA = r'''
ObjC.import('AppKit');
function run(argv) {
    var front = $.NSWorkspace.sharedWorkspace.frontmostApplication;
    var instances = [];
    var apps = $.NSWorkspace.sharedWorkspace.runningApplications;
    for (var i = 0; i < Number(apps.count); i++) {
        var app = apps.objectAtIndex(i);
        if (ObjC.unwrap(app.bundleIdentifier) === argv[0]) instances.push(Number(app.processIdentifier));
    }
    return JSON.stringify({frontmost_available: Boolean(front && !front.isNil()), existing_pids: instances});
}
'''
PROBE_JXA = r'''
ObjC.import('AppKit');
function run(argv) {
    var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(parseInt(argv[0], 10));
    if (!app || app.isNil()) return JSON.stringify({found: false});
    return JSON.stringify({found: true, pid: Number(app.processIdentifier),
        bundle_id: ObjC.unwrap(app.bundleIdentifier), executable: ObjC.unwrap(app.executableURL.path),
        finished_launching: Boolean(app.isFinishedLaunching), terminated: Boolean(app.isTerminated),
        activation_policy: Number(app.activationPolicy)});
}
'''


def jxa(source, argument):
    result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", source, str(argument)],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError("AppKit 会话检查失败：" + result.stderr.strip())
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="验证过的、待发布的 Compositor-zh-CN.app")
    parser.add_argument("--seconds", type=float, default=12, help="持续观察时间，至少 10 秒，默认 12")
    parser.add_argument("--bundle-id", default="local.compositor.zhcn")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "build/logs")
    args = parser.parse_args()
    if not 10 <= args.seconds <= 120:
        parser.error("--seconds 必须在 10 至 120 秒之间")
    args.log_dir.mkdir(parents=True, exist_ok=True)
    report = {"status": "FAIL", "ui_review": "NOT VERIFIED", "snapshots": [],
              "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "requested_observation_seconds": args.seconds}
    process = None
    log_path = args.log_dir / "smoke-launch-app.log"
    try:
        if platform.system() != "Darwin":
            raise ValueError("启动检查需要真实 macOS GUI 会话")
        app, info, executable = bundle_info(args.app)
        report.update(app=str(app), executable=str(executable), bundle_id=info.get("CFBundleIdentifier"))
        if info.get("CFBundleIdentifier") != args.bundle_id:
            raise ValueError("独立 Bundle ID 不匹配")
        # Fail before launch in SSH/headless contexts; never request Automation or Screen Recording access.
        if os.stat("/dev/console").st_uid != os.geteuid():
            raise ValueError("当前用户不是 macOS 控制台用户，无法验证 GUI 启动")
        session = jxa(PREFLIGHT_JXA, args.bundle_id)
        report["session"] = session
        if not session["frontmost_available"]:
            raise ValueError("没有可访问的 macOS GUI 会话，无法验证启动")
        if session["existing_pids"]:
            raise ValueError("同一 Bundle ID 的 App 已运行，请先自行退出再测试；检查不会终止已有实例")
        with log_path.open("w", encoding="utf-8") as app_log:
            # Popen owns the exact PID: no open/pkill/killall, and no saved preferences are modified.
            process = subprocess.Popen([str(executable), "-CompositorChineseEnabled", "YES",
                                        "-AppleLanguages", "(zh-Hans,en)"], cwd=str(app.parent),
                                       stdout=app_log, stderr=subprocess.STDOUT)
            started = time.monotonic()
            report["pid"] = process.pid
            print("已启动独立进程 PID " + str(process.pid) + "，观察至少 " + str(args.seconds) + " 秒", flush=True)
            while True:
                elapsed = time.monotonic() - started
                if process.poll() is not None:
                    report["app_exit_code"] = process.returncode
                    raise ValueError("App 提前退出，exit code=" + str(process.returncode) + "；详见 " + str(log_path))
                state = jxa(PROBE_JXA, process.pid)
                state["elapsed_seconds"] = round(time.monotonic() - started, 3)
                report["snapshots"].append(state)
                if state.get("found"):
                    if state.get("pid") != process.pid or state.get("bundle_id") != args.bundle_id:
                        raise ValueError("AppKit 返回的进程身份不匹配")
                    if Path(state.get("executable", "")).resolve() != executable:
                        raise ValueError("AppKit 进程对应另一份 App")
                    if state.get("terminated"):
                        raise ValueError("AppKit 报告 App 已终止")
                if elapsed >= args.seconds:
                    if not state.get("found") or not state.get("finished_launching"):
                        raise ValueError("进程存活，但 AppKit 未确认完成启动")
                    if state.get("activation_policy") != 0:
                        raise ValueError("AppKit 未确认普通 GUI App 的启动状态")
                    if process.poll() is not None:
                        raise ValueError("App 在最终检查时退出")
                    report["observed_seconds"] = round(time.monotonic() - started, 3)
                    report["status"] = "PASS"
                    report["scope"] = "指定 PID 持续存活且 AppKit isFinishedLaunching=true；未验证窗口、中文显示或编辑功能"
                    break
                time.sleep(min(1, max(0.05, args.seconds - (time.monotonic() - started))))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print("启动检查失败：" + str(error), file=sys.stderr)
    finally:
        # Only terminate the process we started; never touch matching names, other PIDs or Gatekeeper.
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            report["test_process_cleaned_up"] = True
        report_path = args.log_dir / "smoke-launch.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        return 1
    print("启动检查通过：" + report["scope"])
    print("报告：" + str(report_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
