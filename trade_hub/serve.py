# -*- coding: utf-8 -*-
"""淘物集市 · 一键启动
流程：
  1.（可选）若 push_notify/messages/raw 中有比 ready_to_label.jsonl 更新的数据，
     自动调用 push_notify/preprocess.py 重新预处理（需要在有采集数据时使用）
  2. 运行 pipeline/build_site.py 构建静态站点 dist/
  3. 启动本地 HTTP 服务，浏览器访问

用法：
  python serve.py                 # 构建 + 启动服务（默认端口 8642）
  python serve.py --port 9000
  python serve.py --no-build      # 跳过构建直接启动
  python serve.py --no-knn        # 构建时跳过向量复核（更快）

实时采集（可选，需 QQ + NapCat 环境）：
  1. 启动 NapCat（push_notify/start_napcat.bat），WebSocket 端口 3001
  2. 另开终端运行 push_notify/run.py 持续采集
  3. 定期重跑本脚本，新消息即会进入站点
"""
import os
import subprocess
import sys
import http.server
import socketserver
import webbrowser

HUB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HUB)
PUSH = os.path.join(ROOT, "push_notify")
DIST = os.path.join(HUB, "dist")
WEB = os.path.join(HUB, "web")


def newest_mtime(path):
    latest = 0
    if not os.path.isdir(path):
        return 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dp, fn)))
            except OSError:
                pass
    return latest


def maybe_preprocess():
    """raw 中有新数据时重新预处理（容错：失败不阻塞后续构建）"""
    raw = os.path.join(PUSH, "messages", "raw")
    ready = os.path.join(PUSH, "messages", "labeled", "ready_to_label.jsonl")
    if not os.path.exists(ready) or newest_mtime(raw) > os.path.getmtime(ready):
        print("[serve] 检测到新采集数据，运行 preprocess…")
        try:
            subprocess.run([sys.executable, "preprocess.py"], cwd=PUSH, timeout=600, check=True)
        except Exception as e:
            print(f"[serve] 预处理失败（继续用旧数据）: {e}")


def build(extra_args):
    cmd = [sys.executable, os.path.join(HUB, "pipeline", "build_site.py")] + extra_args
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("[serve] 构建失败，若 dist/ 已存在旧版本将继续提供服务")
    # 同步前端最新文件
    if os.path.isdir(WEB):
        import shutil
        for name in os.listdir(WEB):
            src, dst = os.path.join(WEB, name), os.path.join(DIST, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                os.makedirs(DIST, exist_ok=True)
                shutil.copy2(src, dst)


def main():
    args = sys.argv[1:]
    port = 8642
    if "--port" in args:
        i = args.index("--port")
        port = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    if "--no-build" not in args:
        maybe_preprocess()
        build([a for a in args if a.startswith("--")])
    else:
        args.remove("--no-build")

    if not os.path.isdir(DIST):
        print("dist/ 不存在，请先运行构建")
        sys.exit(1)

    os.chdir(DIST)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), Quiet) as httpd:
        url = f"http://localhost:{port}"
        print(f"[serve] 淘物集市已启动: {url}（局域网设备可用本机 IP 访问）")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] 已停止")


if __name__ == "__main__":
    main()
