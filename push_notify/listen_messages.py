# 注意：原文件中的真实 QQ 群号已脱敏为占位符，请替换为你自己的群号后使用
"""
QQ群消息智能监听工具 v2
功能：
  1. 只监听指定群（白名单）
  2. 消息分类标签（交易出售/交易求购/闲聊/通知）
  3. 关键词提醒（命中关键词的消息高亮+声音提醒）
  4. 消息保存到JSONL文件
  5. 统计摘要

使用前：
  1. 确保NapCat已启动并配置了WebSocket服务端（端口3001）
  2. 修改下方配置区的参数
  3. 安装依赖：pip install -r requirements.txt
  4. 运行：python listen_messages.py
"""

import json
import os
import socket
import sys
import time
from datetime import datetime
from collections import defaultdict

import websocket  # pip install websocket-client

# ============ 配置区 ============

NAPCAT_WS_URL = "ws://127.0.0.1:3001"
ACCESS_TOKEN = ""

# 只监听这些群（填群号，留空=监听所有群）
# 从你的日志看，你有这些群：
#   <QQ_GROUP_ID> - 先进信息研究所2025级
#   <QQ_GROUP_ID>  - 西电杭州研究院聊天群
WATCH_GROUPS = [
    # <QQ_GROUP_ID>,
    # <QQ_GROUP_ID>,
]  # 先留空，后面你想监听哪个群就填哪个

# 关键词提醒：群里出现这些词时，高亮 + 响铃
ALERT_KEYWORDS = [
    "二手", "出售", "出", "转让", "闲置",
    "求购", "求", "收", "想要",
    "电动车", "自行车", "教材", "书", "电脑", "手机",
    "免费送", "便宜", "低价",
]

# ====== 我想找的物品（订阅提醒）======
# 不需要改代码！打开同目录下的 config.txt 文件，在里面填写想找的物品即可
# 系统启动时会自动读取 config.txt
WANT_ITEMS = []

# 从 config.txt 读取订阅物品
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                WANT_ITEMS.append(line)
    if WANT_ITEMS:
        print(f"  从 config.txt 读取到 {len(WANT_ITEMS)} 个订阅物品: {', '.join(WANT_ITEMS)}")
    else:
        print(f"  config.txt 存在但未填写订阅物品（去掉行前的 # 号即可启用）")

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

# 出售意图关键词
SELL_KEYWORDS = ["出", "出售", "转让", "闲置", "卖", "清", "免费送", "低价出"]
# 求购意图关键词
BUY_KEYWORDS = ["求", "求购", "收", "想要", "需要", "求购", "找"]
# 通知类关键词（老师/管理员发的通知）
NOTICE_KEYWORDS = ["通知", "公告", "请", "同学", "安排", "报名", "截止", "ddl", "DDL"]

# 消息保存路径
SAVE_DIR = "messages"
SAVE_FILE = os.path.join(SAVE_DIR, f"messages_{datetime.now().strftime('%Y%m%d')}.jsonl")
STATS_FILE = os.path.join(SAVE_DIR, f"stats_{datetime.now().strftime('%Y%m%d')}.json")

# 图片下载
DOWNLOAD_IMAGES = True
IMAGES_DIR = os.path.join(SAVE_DIR, "images")

# ================================


def download_image(url, save_path):
    """下载图片到本地"""
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

# ANSI颜色码
class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

# 统计数据
stats = defaultdict(lambda: {"total": 0, "sell": 0, "buy": 0, "chat": 0, "notice": 0, "alert": 0})


def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)


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


def classify_message(text):
    """简单规则分类消息（后续可替换为BERT模型）"""
    text_lower = text.lower()

    # 检查出售意图
    for kw in SELL_KEYWORDS:
        if kw in text_lower:
            return "sell", "出售"

    # 检查求购意图
    for kw in BUY_KEYWORDS:
        if kw in text_lower:
            return "buy", "求购"

    # 检查通知类
    for kw in NOTICE_KEYWORDS:
        if kw in text_lower:
            return "notice", "通知"

    return "chat", "闲聊"


def check_alert_keywords(text):
    """检查是否命中关键词提醒"""
    hit_keywords = []
    for kw in ALERT_KEYWORDS:
        if kw in text:
            hit_keywords.append(kw)
    return hit_keywords


def check_want_items(text):
    """
    检查是否命中用户订阅的想要物品（含同义词扩展）
    返回 [{"item": "自行车", "matched_word": "山地车"}, ...]
    """
    hits = []
    text_lower = text.lower()
    for item in WANT_ITEMS:
        # 检查主词
        if item.lower() in text_lower:
            hits.append({"item": item, "matched_word": item})
            continue
        # 检查同义词
        for syn in WANT_SYNONYMS.get(item, []):
            if syn.lower() in text_lower:
                hits.append({"item": item, "matched_word": syn})
                break
    return hits


def print_want_alert(text, group_name, sender, time_str, want_hits):
    """打印订阅物品命中提醒（比普通关键词提醒更醒目）"""
    print()
    print(f"{Color.BOLD}{Color.MAGENTA}{'='*60}{Color.RESET}")
    print(f"{Color.BOLD}{Color.MAGENTA}  ★★★ 你想找的物品出现了！{Color.RESET}")
    for h in want_hits:
        print(f"{Color.MAGENTA}  → {h['item']}（匹配到: {h['matched_word']}）{Color.RESET}")
    print(f"{Color.YELLOW}  [{time_str}] [{group_name}] {sender}{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}  内容: {text}{Color.RESET}")
    print(f"{Color.MAGENTA}{'='*60}{Color.RESET}")
    print()
    # 响铃3次（比普通提醒更急）
    sys.stdout.write('\a\a\a')
    sys.stdout.flush()


def print_alert(text, group_name, sender, time_str, keywords):
    """高亮打印关键词提醒"""
    print()
    print(f"{Color.BOLD}{Color.RED}{'='*60}{Color.RESET}")
    print(f"{Color.BOLD}{Color.RED}  ⚠️  关键词提醒！{Color.RESET}")
    print(f"{Color.RED}  命中关键词: {', '.join(keywords)}{Color.RESET}")
    print(f"{Color.YELLOW}  [{time_str}] [{group_name}] {sender}{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}  内容: {text}{Color.RESET}")
    print(f"{Color.RED}{'='*60}{Color.RESET}")
    print()
    # 响铃
    sys.stdout.write('\a')
    sys.stdout.flush()


def print_message(text, group_id, group_name, sender, time_str, category, cat_label):
    """按分类用不同颜色打印消息"""
    color_map = {
        "sell": Color.GREEN,
        "buy": Color.YELLOW,
        "notice": Color.BLUE,
        "chat": Color.RESET,
    }
    color = color_map.get(category, Color.RESET)
    cat_tag = f"[{cat_label}]" if category != "chat" else ""
    print(f"{color}[{time_str}] [{group_name}] {sender} {cat_tag}: {text}{Color.RESET}")


def save_message(record):
    ensure_save_dir()
    with open(SAVE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_stats(group_id, category, has_alert):
    stats[group_id]["total"] += 1
    stats[group_id][category] += 1
    if has_alert:
        stats[group_id]["alert"] += 1


def save_stats():
    ensure_save_dir()
    stats_data = {
        str(gid): dict(s) for gid, s in stats.items()
    }
    stats_data["_updated"] = datetime.now().isoformat()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats_data, f, ensure_ascii=False, indent=2)


def on_message(ws, message):
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

    # 下载图片（与 fetch_history.py 保持一致的文件名格式）
    if DOWNLOAD_IMAGES and isinstance(message_segments, list):
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
                    if download_image(img_url, img_path):
                        pass  # 下载成功

    # 分类
    category, cat_label = classify_message(text)

    # 关键词检查
    hit_keywords = check_alert_keywords(text)
    
    # 订阅物品检查（最高优先级）
    want_hits = check_want_items(text)

    # 时间
    time_str = datetime.fromtimestamp(msg_time).strftime("%H:%M:%S")

    # 打印（订阅提醒 > 关键词提醒 > 普通打印）
    if want_hits:
        print_want_alert(text, group_name, display_name, time_str, want_hits)
    elif hit_keywords:
        print_alert(text, group_name, display_name, time_str, hit_keywords)
    else:
        print_message(text, group_id, group_name, display_name, time_str, category, cat_label)

    # 统计
    update_stats(group_id, category, bool(hit_keywords))

    # 保存完整格式（与 fetch_history.py 的 raw 格式对齐，供 preprocess.py 处理）
    record = {
        "message_id": msg_id,
        "message_seq": msg_seq,
        "time": msg_time,
        "time_str": time_str,
        "group_id": group_id,
        "group_name": group_name,
        "user_id": user_id,
        "sender": sender,
        "message": message_segments,  # 完整消息段（表情包过滤、多商品拆分依赖此字段）
        "raw_message": raw_message,
        # 以下为监听脚本额外信息，preprocess.py 不依赖
        "category": category,
        "alert_keywords": hit_keywords,
        "want_hits": want_hits,
    }
    save_message(record)


def on_error(ws, error):
    print(f"{Color.RED}[错误] {error}{Color.RESET}")


def on_close(ws, close_status, close_msg):
    print(f"\n{Color.YELLOW}[断开] 连接已关闭 (code={close_status}){Color.RESET}")
    save_stats()


def on_open(ws):
    print(f"{Color.GREEN}{'='*60}{Color.RESET}")
    print(f"{Color.GREEN}  连接成功！开始监听QQ群消息{Color.RESET}")
    print(f"  消息保存到: {SAVE_FILE}")
    print(f"  统计保存到: {STATS_FILE}")
    if WATCH_GROUPS:
        print(f"  只监听群: {WATCH_GROUPS}")
    else:
        print(f"  监听所有群")
    print(f"  关键词提醒: {len(ALERT_KEYWORDS)} 个关键词")
    if WANT_ITEMS:
        print(f"  {Color.MAGENTA}订阅提醒: {len(WANT_ITEMS)} 个物品 → {', '.join(WANT_ITEMS)}{Color.RESET}")
    else:
        print(f"  订阅提醒: 未设置（在 WANT_ITEMS 中添加你想找的物品）")
    print(f"  图片下载: {'是' if DOWNLOAD_IMAGES else '否'}")
    print(f"  消息分类: 出售(绿) / 求购(黄) / 通知(蓝) / 闲聊(白)")
    print(f"  按 Ctrl+C 退出")
    print(f"{Color.GREEN}{'='*60}{Color.RESET}")
    print()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 3001

    print(f"正在检查 {host}:{port} ...")
    if not check_port(host, port):
        print()
        print(f"{Color.RED}[错误] 端口 3001 不可达！{Color.RESET}")
        print("请确认NapCat正在运行，且WebSocket服务端已启用。")
        print("启动NapCat: 双击 C:\\NapCat\\launcher.bat")
        exit(1)

    print(f"端口 {port} 可达，正在连接 WebSocket ...")

    url = NAPCAT_WS_URL
    header = []
    if ACCESS_TOKEN:
        header.append(f"Authorization: Bearer {ACCESS_TOKEN}")

    ws = websocket.WebSocketApp(
        url,
        header=header,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    try:
        ws.run_forever(reconnect=5)
    except KeyboardInterrupt:
        print("\n正在保存统计数据...")
        save_stats()
        print("已退出")
        print(f"今日统计已保存到: {STATS_FILE}")
