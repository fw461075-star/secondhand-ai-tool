"""
内网穿透模块
支持 cpolar / ngrok / cloudflared
自动检测已安装的工具，启动隧道，返回公网URL
"""

import subprocess
import re
import time
import sys
import os

TUNNEL_PORT = 8765
_tunnel_process = None
_public_url = None


def find_tunnel_tool():
    """检测已安装的内网穿透工具，返回 (名称, 完整路径或命令名)"""
    tools = [
        ("cpolar", [r"C:\software\cpolar\cpolar.exe", "cpolar"]),
        ("ngrok", ["ngrok"]),
        ("cloudflared", ["cloudflared"]),
    ]
    import shutil
    for name, cmds in tools:
        for cmd in cmds:
            if os.sep in cmd:
                if os.path.isfile(cmd):
                    return name, cmd
            else:
                if shutil.which(cmd):
                    return name, cmd
    return None, None


def _query_cpolar_api():
    """通过cpolar Web API查询隧道URL"""
    import urllib.request
    import json
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:9200/api/tunnels",
            headers={"Accept": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        data = json.loads(resp.read())
        for t in data.get("items", []):
            if str(TUNNEL_PORT) in str(t.get("local_addr", "")):
                return t.get("public_url", "")
    except:
        pass
    return None


def _query_cpolar_logs():
    """从cpolar日志文件读取隧道URL（备用方案）"""
    import glob
    import re
    log_dir = os.path.join(os.path.expanduser("~"), ".cpolar", "logs")
    if not os.path.isdir(log_dir):
        return None
    
    # 找最新的日志文件
    log_files = sorted(glob.glob(os.path.join(log_dir, "cpolar_service.log*")), key=os.path.getmtime, reverse=True)
    
    for log_file in log_files[:3]:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                # 匹配隧道URL: https://xxx.cpolar.top (排除api.cpolar.com等官方域名)
                # 隧道URL有随机子域名如 45b18d81.r32.cpolar.top
                pattern = r'https?://[a-z0-9]+\.[a-z0-9]+\.cpolar\.[a-z]+'
                matches = re.findall(pattern, content)
                if matches:
                    # 找最新的https
                    for m in reversed(matches):
                        if m.startswith('https://'):
                            return m
                    return matches[-1]
        except:
            pass
    return None


def start_cpolar(port, cmd="cpolar"):
    """启动cpolar隧道"""
    global _tunnel_process, _public_url
    import urllib.request
    import json

    # 先检查cpolar Web UI是否已经在运行
    web_ui_running = False
    try:
        urllib.request.urlopen("http://127.0.0.1:9200", timeout=2)
        web_ui_running = True
    except:
        pass

    if not web_ui_running:
        # 启动cpolar守护进程
        print("  [cpolar] 启动守护进程...")
        _tunnel_process = subprocess.Popen(
            [cmd, "start-all", "-dashboard=on"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # 等待Web UI启动
        for _ in range(20):
            time.sleep(0.5)
            try:
                urllib.request.urlopen("http://127.0.0.1:9200", timeout=2)
                web_ui_running = True
                break
            except:
                pass

    if not web_ui_running:
        print("  [cpolar] Web UI启动失败")
        return None

    # 检查是否已有指向该端口的隧道
    url = _query_cpolar_api()
    if not url:
        # API查询失败，尝试从日志读取
        url = _query_cpolar_logs()
    if url:
        _public_url = url
        return url

    # 没有的话，通过API创建隧道
    print("  [cpolar] 创建HTTP隧道...")
    try:
        data = json.dumps({
            "name": "二手交易",
            "proto": "http",
            "local_addr": f"localhost:{port}"
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:9200/api/tunnels",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        url = result.get("public_url", "")
        if url:
            _public_url = url
            return url
    except Exception as e:
        print(f"  [cpolar] API创建隧道失败: {e}")

    # 兜底：等几秒再查一次
    time.sleep(3)
    url = _query_cpolar_api()
    if url:
        _public_url = url
    return url


def start_ngrok(port):
    """启动ngrok隧道"""
    global _tunnel_process, _public_url
    _tunnel_process = subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    time.sleep(3)
    try:
        import urllib.request
        import json
        resp = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=5)
        data = json.loads(resp.read())
        if data.get("tunnels"):
            _public_url = data["tunnels"][0]["public_url"]
            return _public_url
    except Exception as e:
        print(f"  [ngrok] 获取URL失败: {e}")
    return None


def start_cloudflared(port):
    """启动cloudflared隧道"""
    global _tunnel_process, _public_url
    _tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start_time = time.time()
    while time.time() - start_time < 30:
        line = _tunnel_process.stdout.readline()
        if not line:
            time.sleep(0.5)
            continue
        print(f"  [cloudflared] {line.strip()}")
        match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
        if match:
            _public_url = match.group(0)
            return _public_url
    return None


def start_tunnel(port=TUNNEL_PORT):
    """
    自动检测并启动内网穿透隧道
    返回公网URL，失败返回None
    """
    tool_name, tool_cmd = find_tunnel_tool()
    if not tool_name:
        print("\n" + "=" * 60)
        print("  未检测到内网穿透工具！")
        print("  手机只能通过局域网访问（同一WiFi）")
        print()
        print("  方案1: cpolar（推荐，免费）")
        print("    1. 下载: https://www.cpolar.com/download")
        print("    2. 注册账号，获取authtoken")
        print("    3. 运行: cpolar authtoken YOUR_TOKEN")
        print("    4. 在Web UI http://127.0.0.1:9200 创建隧道")
        print("=" * 60 + "\n")
        return None

    print(f"\n[内网穿透] 检测到 {tool_name}，正在启动隧道...")

    if tool_name == "cpolar":
        url = start_cpolar(port, tool_cmd)
    elif tool_name == "ngrok":
        url = start_ngrok(port)
    elif tool_name == "cloudflared":
        url = start_cloudflared(port)
    else:
        return None

    if url:
        print(f"\n[内网穿透] 公网地址: {url}")
        print(f"[内网穿透] 手机在任何网络下都可访问此地址\n")
        return url
    else:
        print(f"\n[内网穿透] 启动失败\n")
        return None


def get_public_url():
    """获取当前公网URL"""
    return _public_url


def stop_tunnel():
    """停止隧道"""
    global _tunnel_process
    if _tunnel_process:
        _tunnel_process.terminate()
        _tunnel_process = None
        print("[内网穿透] 隧道已关闭")


if __name__ == "__main__":
    url = start_tunnel()
    if url:
        print(f"\n公网地址: {url}")
        print("按Ctrl+C退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_tunnel()
    else:
        sys.exit(1)
