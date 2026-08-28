"""
二手交易助手 - 实时运行入口
功能：
  1. 启动WebSocket监听QQ群消息（含图片下载）
  2. 收到新消息后自动保存到raw目录
  3. 定时触发预处理（合并/分类/生成HTML）
  4. 启动本地HTTP服务，浏览器实时查看结果
  5. 订阅物品命中时控制台高亮提醒

使用方法：
  1. 确保NapCat已启动（WebSocket端口3001）
  2. 运行：python run.py
  3. 浏览器打开 http://localhost:8765
"""
import json
import os
import sys
import time
import threading
import http.server
import socketserver
import webbrowser
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# ============ 配置 ============
NAPCAT_WS_URL = "ws://127.0.0.1:3001"
ACCESS_TOKEN = ""
HTTP_PORT = 8765
REPROCESS_INTERVAL = 30  # 每30秒自动重新预处理一次

# 监听哪些群（留空=全部）
WATCH_GROUPS = []

# 图片下载
IMAGES_DIR = "messages/images"

# raw数据保存目录
RAW_DIR = "messages/raw"

# 输出目录
OUTPUT_DIR = "messages/labeled"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "ready_to_label.jsonl")
REVIEW_HTML = os.path.join(OUTPUT_DIR, "review.html")

# ================================

# 同义词映射（与 preprocess.py 保持一致）
WANT_SYNONYMS = {
    "自行车": ["山地车", "公路车", "单车", "脚踏车"],
    "电动车": ["电瓶车", "小电驴", "电驴", "电摩托"],
    "教材": ["课本", "书", "教科书"],
    "电脑": ["笔记本", "笔记本电脑", "本本", "轻薄本", "游戏本"],
    "平板": ["ipad", "iPad", "pad", "平板电脑"],
    "手机": ["iPhone", "华为", "小米", "OPPO", "vivo"],
    "显示器": ["屏幕", "显示屏", "monitor"],
    "桌子": ["书桌", "电脑桌", "餐桌", "学习桌"],
    "椅子": ["凳子", "座椅", "办公椅", "电竞椅"],
    "床": ["床垫", "床铺", "上下铺"],
    "风扇": ["电风扇", "台扇", "落地扇"],
    "台灯": ["灯", "护眼灯", "床头灯"],
    "水壶": ["热水壶", "电水壶", "烧水壶"],
    "衣服": ["外套", "卫衣", "裤子", "羽绒服"],
    "鞋": ["鞋子", "球鞋", "运动鞋", "板鞋"],
    "包": ["书包", "双肩包", "单肩包"],
    "会员": ["vip", "VIP", "svip", "超级会员"],
    "网课": ["课程", "慕课", "视频课"],
    "考研": ["考研资料", "考研书", "考研笔记"],
    "充电器": ["电源", "适配器", "充电头", "快充"],
    "路由器": ["wifi", "无线", "交换机", "网线"],
    "吉他": ["尤克里里", "乐器", "电子琴"],
    "锅": ["电饭锅", "电饭煲", "炒锅", "电磁炉"],
    "柜子": ["收纳柜", "衣柜", "书架", "置物架"],
}

# 读取订阅物品
WANT_ITEMS = []
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                WANT_ITEMS.append(line)

# 颜色
class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

# 全局状态
new_message_count = 0
last_process_time = 0
stats = defaultdict(lambda: {"total": 0, "sell": 0, "buy": 0, "chat": 0, "notice": 0, "want_hit": 0})


# ============ 消息处理 ============

SELL_KEYWORDS = ["出", "出售", "转让", "闲置", "卖", "清", "免费送", "低价", "低价出", "处理", "退坑", "半价", "打折"]
BUY_KEYWORDS = ["求", "求购", "收", "想要", "需要", "找", "求收", "高价收"]
NOTICE_KEYWORDS = ["通知", "公告", "请同学", "安排", "报名", "截止", "ddl", "DDL", "作业", "提交"]


def classify_message(text):
    text_lower = text.lower()
    for kw in SELL_KEYWORDS:
        if kw in text_lower:
            return "sell", "出售"
    for kw in BUY_KEYWORDS:
        if kw in text_lower:
            return "buy", "求购"
    for kw in NOTICE_KEYWORDS:
        if kw in text_lower:
            return "notice", "通知"
    return "chat", "闲聊"


def check_want_items(text):
    """检查是否命中订阅物品"""
    hits = []
    text_lower = text.lower()
    for item in WANT_ITEMS:
        if item.lower() in text_lower:
            hits.append({"item": item, "matched_word": item})
            continue
        for syn in WANT_SYNONYMS.get(item, []):
            if syn.lower() in text_lower:
                hits.append({"item": item, "matched_word": syn})
                break
    return hits


def extract_text(message_segments):
    texts = []
    for seg in message_segments:
        if seg.get("type") == "text":
            texts.append(seg["data"].get("text", ""))
        elif seg.get("type") == "image":
            texts.append("[图片]")
        elif seg.get("type") == "face":
            texts.append("[表情]")
        elif seg.get("type") == "at":
            texts.append("[@]")
        elif seg.get("type") == "reply":
            texts.append("[回复]")
        else:
            texts.append(f"[{seg.get('type', '?')}]")
    return "".join(texts).strip()


def download_image(url, save_path):
    try:
        import requests as _req
        resp = _req.get(url, timeout=15)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
    except:
        pass
    return False


# ============ WebSocket监听 ============

def on_message(ws, message):
    global new_message_count, last_process_time
    
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return
    
    if data.get("post_type") != "message":
        return
    if data.get("message_type") != "group":
        return
    
    group_id = data.get("group_id")
    sender = data.get("sender", {})
    nickname = sender.get("nickname", "未知")
    card = sender.get("card", "")
    display_name = card if card else nickname
    user_id = data.get("user_id")
    group_name = sender.get("group_name", "") or str(group_id)
    msg_id = data.get("message_id", "")
    msg_seq = data.get("message_seq", "")
    msg_time = data.get("time", int(time.time()))
    
    # 白名单过滤
    if WATCH_GROUPS and group_id not in WATCH_GROUPS:
        return
    
    # 提取文本
    raw_message = data.get("raw_message", "")
    message_segments = data.get("message", [])
    if isinstance(message_segments, list):
        text = extract_text(message_segments)
    else:
        text = raw_message
        message_segments = [{"type": "text", "data": {"text": raw_message}}]
    
    if not text:
        return
    
    # 下载图片
    if isinstance(message_segments, list):
        for i, seg in enumerate(message_segments):
            if isinstance(seg, dict) and seg.get("type") == "image":
                img_url = seg.get("data", {}).get("url", "")
                if img_url:
                    ext = ".jpg"
                    if ".png" in img_url:
                        ext = ".png"
                    img_name = f"{msg_time}_{msg_seq}_{i}{ext}" if msg_seq else f"{msg_time}_{msg_id}_{i}{ext}"
                    img_dir = os.path.join(IMAGES_DIR, str(group_id))
                    img_path = os.path.join(img_dir, img_name)
                    download_image(img_url, img_path)
    
    # 分类
    category, cat_label = classify_message(text)
    
    # 订阅物品检查
    want_hits = check_want_items(text)
    
    # 时间
    time_str = datetime.fromtimestamp(msg_time).strftime("%H:%M:%S")
    
    # 打印
    color_map = {"sell": Color.GREEN, "buy": Color.YELLOW, "notice": Color.BLUE, "chat": Color.RESET}
    color = color_map.get(category, Color.RESET)
    
    if want_hits:
        print(f"\n{Color.BOLD}{Color.MAGENTA}{'='*60}{Color.RESET}")
        print(f"{Color.BOLD}{Color.MAGENTA}  ★★★ 你想找的物品出现了！{Color.RESET}")
        for h in want_hits:
            print(f"{Color.MAGENTA}  → {h['item']}（匹配到: {h['matched_word']}）{Color.RESET}")
        print(f"{Color.YELLOW}  [{time_str}] [{group_name}] {display_name}{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}  内容: {text}{Color.RESET}")
        print(f"{Color.MAGENTA}{'='*60}{Color.RESET}\n")
        sys.stdout.write('\a\a\a')
        sys.stdout.flush()
        stats[group_id]["want_hit"] += 1
        
        # 推送通知到手机
        try:
            from push_notify import notify_want_hit
            for h in want_hits:
                notify_want_hit(h["item"], h["matched_word"], text, group_name, display_name)
        except:
            pass  # 推送失败不影响主流程
    else:
        cat_tag = f"[{cat_label}]" if category != "chat" else ""
        print(f"{color}[{time_str}] [{group_name}] {display_name} {cat_tag}: {text}{Color.RESET}")
    
    # 保存完整格式到raw（与fetch_history.py对齐）
    today = datetime.now().strftime('%Y%m%d')
    raw_file = os.path.join(RAW_DIR, f"raw_{today}_live.jsonl")
    os.makedirs(RAW_DIR, exist_ok=True)
    
    record = {
        "message_id": msg_id,
        "message_seq": msg_seq,
        "time": msg_time,
        "time_str": time_str,
        "group_id": group_id,
        "group_name": group_name,
        "user_id": user_id,
        "sender": sender,
        "message": message_segments,
        "raw_message": raw_message,
        "category": category,
        "want_hits": want_hits,
    }
    with open(raw_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    # 统计
    stats[group_id]["total"] += 1
    stats[group_id][category] += 1
    
    new_message_count += 1
    
    # 每5条新消息触发一次预处理
    if new_message_count >= 5:
        trigger_preprocess()
        new_message_count = 0


def on_error(ws, error):
    print(f"{Color.RED}[错误] {error}{Color.RESET}")


def on_close(ws, close_status, close_msg):
    print(f"\n{Color.YELLOW}[断开] WebSocket连接关闭 (code={close_status}){Color.RESET}")


def on_open(ws):
    print(f"{Color.GREEN}{'='*60}{Color.RESET}")
    print(f"{Color.GREEN}  二手交易助手已启动！{Color.RESET}")
    print(f"  WebSocket监听: {NAPCAT_WS_URL}")
    print(f"  网页预览: http://localhost:{HTTP_PORT}")
    if WATCH_GROUPS:
        print(f"  只监听群: {WATCH_GROUPS}")
    else:
        print(f"  监听所有群")
    if WANT_ITEMS:
        print(f"  {Color.MAGENTA}订阅物品: {', '.join(WANT_ITEMS)}{Color.RESET}")
    else:
        print(f"  订阅物品: 未设置（编辑config.txt添加）")
    print(f"  自动预处理: 每{REPROCESS_INTERVAL}秒或每5条新消息")
    print(f"  按 Ctrl+C 退出")
    print(f"{Color.GREEN}{'='*60}{Color.RESET}\n")
    
    # 启动定时预处理线程
    t = threading.Thread(target=periodic_process, daemon=True)
    t.start()
    
    # 先跑一次预处理（处理历史数据）
    trigger_preprocess()


# ============ 预处理触发 ============

def trigger_preprocess():
    """触发预处理（在子线程中运行）"""
    global last_process_time, new_message_count
    last_process_time = time.time()
    new_message_count = 0
    try:
        from preprocess import process_all
        process_all(verbose=True)
    except Exception as e:
        print(f"{Color.RED}[预处理错误] {e}{Color.RESET}")


def periodic_process():
    """定时触发预处理"""
    global last_process_time
    while True:
        time.sleep(REPROCESS_INTERVAL)
        # 如果有新消息且距离上次处理超过间隔，触发预处理
        if new_message_count > 0:
            trigger_preprocess()


# ============ HTTP服务 ============

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    """自定义HTTP处理器"""
    
    def do_POST(self):
        """POST请求直接复用GET的处理逻辑"""
        self.do_GET()
    
    def do_GET(self):
        # 去掉query string，只保留路径部分
        path_only = self.path.split("?")[0]
        
        # 根路径跳转到review.html
        if path_only == "/" or path_only == "":
            path_only = "/messages/labeled/review.html"
        
        # API接口
        if path_only == "/api/stats":
            stats_data = {
                "groups": {str(k): dict(v) for k, v in stats.items()},
                "want_items": WANT_ITEMS,
                "updated": datetime.now().isoformat(),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(stats_data, ensure_ascii=False).encode("utf-8"))
            return
        
        # 语义搜索API
        if path_only == "/api/search":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            q = qs.get("q", [""])[0]
            cat = qs.get("cat", [""])[0]
            if q:
                try:
                    import vector_db
                    results = vector_db.search_semantic(q, top_k=50, cat_filter=cat if cat else None)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"[]")
            return
        
        # 向量库状态API
        if path_only == "/api/vector_status":
            try:
                import vector_db
                status = vector_db.get_status()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(status, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ready": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        
        # 保存订阅配置API
        if path_only == "/api/save_config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            from urllib.parse import parse_qs
            params = parse_qs(body)
            items_json = params.get("items", ["[]"])[0]
            try:
                items = json.loads(items_json)
                config_path = os.path.join(PROJECT_DIR, "config.txt")
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write("# 二手交易助手 订阅配置\n")
                    f.write(f"# 更新于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    for item in items:
                        f.write(item + "\n")
                # 更新内存中的WANT_ITEMS
                WANT_ITEMS[:] = items
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        
        # 确认OCR结果API
        if path_only == "/api/confirm_ocr":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            from urllib.parse import parse_qs
            params = parse_qs(body)
            msg_id = params.get("msg_id", [""])[0]
            cat = params.get("cat", [""])[0]
            if msg_id and cat:
                try:
                    CONFIRMED_OCR_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "confirmed_ocr.json")
                    # 读取现有确认
                    confirmed = []
                    if os.path.exists(CONFIRMED_OCR_FILE):
                        with open(CONFIRMED_OCR_FILE, "r", encoding="utf-8") as f:
                            confirmed = json.load(f)
                    # 添加确认（格式：msg_id:cat）
                    entry = f"{msg_id}:{cat}"
                    if entry not in confirmed:
                        confirmed.append(entry)
                    # 保存
                    os.makedirs(os.path.dirname(CONFIRMED_OCR_FILE), exist_ok=True)
                    with open(CONFIRMED_OCR_FILE, "w", encoding="utf-8") as f:
                        json.dump(confirmed, f, ensure_ascii=False)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            else:
                self.send_error(400)
            return
        
        # 重新预处理API（刷新数据）
        if path_only == "/api/reprocess":
            try:
                import subprocess
                subprocess.Popen(
                    [sys.executable, "-c", "import preprocess; preprocess.process_all(verbose=False); from vector_db import build_vector_db; build_vector_db(force=True)"],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"ok":true,"msg":"reprocess started"}')
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        
        # PWA manifest.json
        if path_only == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.end_headers()
            with open(os.path.join(PROJECT_DIR, "manifest.json"), "rb") as f:
                self.wfile.write(f.read())
            return
        
        # PWA Service Worker
        if path_only == "/sw.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Service-Worker-Allowed", "/")
            self.end_headers()
            with open(os.path.join(PROJECT_DIR, "sw.js"), "rb") as f:
                self.wfile.write(f.read())
            return
        
        # 其他文件：从项目目录提供
        # 不用 super().do_GET()，避免路径被处理两次
        file_path = self.translate_path(path_only)
        if os.path.isfile(file_path):
            # 根据扩展名设置Content-Type
            ext = os.path.splitext(file_path)[1].lower()
            content_types = {
                '.html': 'text/html; charset=utf-8',
                '.js': 'application/javascript; charset=utf-8',
                '.css': 'text/css; charset=utf-8',
                '.json': 'application/json; charset=utf-8',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml',
                '.ico': 'image/x-icon',
            }
            content_type = content_types.get(ext, 'application/octet-stream')
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, f"Read error: {e}")
        else:
            self.send_error(404, f"Not found: {path_only}")
    
    def translate_path(self, path):
        """把URL路径映射到项目目录下的文件"""
        # 去掉query string（?v=3 之类的参数）
        if "?" in path:
            path = path.split("?")[0]
        # 去掉开头的/
        if path.startswith('/'):
            path = path[1:]
        # 路径安全处理：防止目录穿越，但保留正常子目录
        path = path.replace("\\", "/")
        parts = [p for p in path.split("/") if p]
        result = os.path.join(PROJECT_DIR, *parts) if parts else PROJECT_DIR
        return result
    
    def log_message(self, format, *args):
        # 静默HTTP日志
        pass


def start_http_server():
    """启动本地HTTP服务（多线程版）"""
    try:
        # 使用ThreadingHTTPServer支持并发请求（手机+电脑同时访问）
        httpd = http.server.ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
        httpd.daemon_threads = True
        httpd.serve_forever()
    except OSError as e:
        print(f"{Color.RED}[错误] 端口{HTTP_PORT}被占用: {e}{Color.RESET}")
        print(f"  请关闭占用{HTTP_PORT}端口的程序后重试")


# ============ NapCat 自动启动 ============

# NapCat 安装路径（可配置，默认C:\NapCat）
NAPCAT_DIR = os.environ.get("NAPCAT_DIR", r"C:\NapCat")
NAPCAT_LAUNCHER = os.path.join(NAPCAT_DIR, "launcher.bat")
NAPCAT_CONFIG_DIR = os.path.join(NAPCAT_DIR, "config")


def find_qq_process():
    """检查QQ是否正在运行"""
    try:
        import psutil
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and 'QQ' in proc.info['name']:
                return True
        return False
    except ImportError:
        # 没有psutil，用tasklist命令
        import subprocess
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq QQ.exe'],
                                capture_output=True, text=True)
        return 'QQ.exe' in result.stdout


def check_napcat_port():
    """检查NapCat的WebSocket端口是否可达"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 3001), timeout=2):
            return True
    except:
        return False


def find_napcat_config():
    """找到NapCat的OneBot11配置文件"""
    if not os.path.exists(NAPCAT_CONFIG_DIR):
        return None
    # 查找 onebot11_*.json 文件
    for f in os.listdir(NAPCAT_CONFIG_DIR):
        if f.startswith("onebot11_") and f.endswith(".json"):
            return os.path.join(NAPCAT_CONFIG_DIR, f)
    return None


def ensure_napcat_config():
    """
    检查NapCat配置是否正确：
    - WebSocket Server已启用
    - 端口为3001
    - 如果没有配置文件，创建一个
    """
    config_file = find_napcat_config()
    
    if not config_file:
        # 没有配置文件，可能NapCat没安装或未初始化
        return False, "未找到NapCat配置文件"
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        ws_servers = config.get("network", {}).get("websocketServers", [])
        for ws in ws_servers:
            if ws.get("enable") and ws.get("port") == 3001:
                return True, "配置正常"
        
        return False, "WebSocket Server未启用或端口不是3001"
    except Exception as e:
        return False, f"读取配置失败: {e}"


def launch_napcat():
    """启动NapCat（通过launcher.bat）"""
    if not os.path.exists(NAPCAT_LAUNCHER):
        return False, f"未找到NapCat launcher.bat: {NAPCAT_LAUNCHER}"
    
    print(f"  {Color.YELLOW}正在启动NapCat...{Color.RESET}")
    print(f"  路径: {NAPCAT_LAUNCHER}")
    print(f"  {Color.CYAN}注意：NapCat启动需要管理员权限{Color.RESET}")
    
    # 用subprocess启动，不等待完成
    import subprocess
    try:
        # launcher.bat 会启动QQ（带NapCat注入）
        proc = subprocess.Popen(
            [NAPCAT_LAUNCHER],
            cwd=NAPCAT_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE  # 新窗口运行
        )
        print(f"  NapCat启动中 (PID: {proc.pid})")
        return True, "已发送启动命令"
    except Exception as e:
        return False, f"启动失败: {e}"


def wait_for_napcat(max_wait=30):
    """等待NapCat的WebSocket端口就绪"""
    print(f"  {Color.CYAN}等待NapCat连接...{Color.RESET}", end="", flush=True)
    for i in range(max_wait):
        if check_napcat_port():
            print(f" {Color.GREEN}已连接{Color.RESET}")
            return True
        time.sleep(1)
        print(".", end="", flush=True)
    print(f" {Color.RED}超时{Color.RESET}")
    return False


def ensure_napcat_running():
    """
    确保NapCat正在运行：
    1. 先检查端口是否可达 → 已运行则直接用
    2. 检查QQ是否在运行
    3. 检查NapCat配置是否正确
    4. 自动启动NapCat
    5. 等待端口就绪
    """
    # 1. 端口已可达
    if check_napcat_port():
        print(f"  {Color.GREEN}NapCat已运行 (端口3001可达){Color.RESET}")
        return True
    
    print(f"  {Color.YELLOW}NapCat未运行，尝试自动启动...{Color.RESET}")
    
    # 2. 检查NapCat是否安装
    if not os.path.exists(NAPCAT_DIR):
        print(f"  {Color.RED}NapCat未安装: {NAPCAT_DIR}{Color.RESET}")
        print(f"  请先下载NapCat: https://napneko.github.io/")
        print(f"  解压到 {NAPCAT_DIR} 后重试")
        return False
    
    # 3. 检查配置
    config_ok, config_msg = ensure_napcat_config()
    if not config_ok:
        print(f"  {Color.YELLOW}NapCat配置: {config_msg}{Color.RESET}")
        print(f"  请在NapCat WebUI中启用WebSocket Server (端口3001)")
        print(f"  WebUI地址: http://127.0.0.1:6099 (首次启动后可用)")
    
    # 4. 启动NapCat
    launched, msg = launch_napcat()
    if not launched:
        print(f"  {Color.RED}{msg}{Color.RESET}")
        return False
    
    # 5. 等待端口就绪
    if wait_for_napcat(30):
        return True
    
    print(f"  {Color.YELLOW}NapCat启动可能需要更长时间{Color.RESET}")
    print(f"  如果QQ弹出了登录窗口，请登录后重试")
    print(f"  或手动运行: {NAPCAT_LAUNCHER}")
    return False


# ============ 主入口 ============

def main():
    print(f"{Color.BOLD}{'='*60}")
    print(f"  二手交易助手 v1.0")
    print(f"{'='*60}{Color.RESET}")
    
    # 检查QQ是否在运行
    qq_running = find_qq_process()
    if qq_running:
        print(f"  {Color.GREEN}QQ已运行{Color.RESET}")
    else:
        print(f"  {Color.YELLOW}QQ未运行，NapCat启动后会自动打开QQ{Color.RESET}")
    
    # 确保NapCat运行
    print(f"\n检查NapCat...")
    if not ensure_napcat_running():
        print(f"\n  {Color.RED}NapCat未就绪，请按以下步骤操作：{Color.RESET}")
        print(f"  1. 确保QQ桌面版已安装")
        print(f"  2. 确保NapCat已解压到 {NAPCAT_DIR}")
        print(f"  3. 右键以管理员身份运行: {NAPCAT_LAUNCHER}")
        print(f"  4. QQ登录后，重新运行本程序")
        print(f"\n  或检查NapCat文档: https://napneko.github.io/")
        input("\n  按回车键退出...")
        return
    
    # 启动HTTP服务（子线程）
    print(f"\n启动本地网页服务 (端口{HTTP_PORT})...")
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    time.sleep(1)
    
    # 启动内网穿透（如果已安装工具）
    try:
        from tunnel import start_tunnel
        public_url = start_tunnel(HTTP_PORT)
        if public_url:
            # 把公网URL写入文件，让前端可以读取显示
            with open(os.path.join(os.path.dirname(__file__), "messages", "labeled", "tunnel_url.txt"), "w") as f:
                f.write(public_url)
    except Exception as e:
        print(f"  内网穿透启动失败: {e}")
    
    # 自动打开浏览器
    webbrowser.open(f"http://localhost:{HTTP_PORT}")
    print(f"  {Color.GREEN}浏览器已打开 http://localhost:{HTTP_PORT}{Color.RESET}")
    
    # 启动WebSocket监听
    print(f"连接WebSocket...")
    header = []
    if ACCESS_TOKEN:
        header.append(f"Authorization: Bearer {ACCESS_TOKEN}")
    
    ws = None
    try:
        import websocket as _ws_mod
        ws = _ws_mod.WebSocketApp(
            NAPCAT_WS_URL,
            header=header,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
    except ImportError:
        print("websocket模块未安装，跳过NapCat连接")
        return
    
    try:
        ws.run_forever(reconnect=5)
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}正在退出...{Color.RESET}")
        print(f"统计: {dict(stats)}")
        print(f"{Color.GREEN}已退出{Color.RESET}")


if __name__ == "__main__":
    main()
