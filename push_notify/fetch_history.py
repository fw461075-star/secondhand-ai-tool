# 注意：原文件中的真实 QQ 群号已脱敏为占位符，请替换为你自己的群号后使用
"""
历史消息拉取工具 v3
功能：
  1. 拉取群历史消息（文本+图片）
  2. 原始数据存一份（raw/，含完整API返回）
  3. 筛选后的数据存一份（processed/，分类标注+图片路径）
  4. 自动下载图片到本地
  5. 时间过滤（默认过去14天）

使用前：
  1. 确保NapCat正在运行
  2. 在NapCat WebUI中添加HTTP服务端，端口3000，启用
  3. 运行：python fetch_history.py
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests  # pip install requests

# ============ 配置区 ============

NAPCAT_HTTP_URL = "http://127.0.0.1:3000"
ACCESS_TOKEN = ""

GROUPS_TO_FETCH = [
    <QQ_GROUP_ID>,   # 26安徽大学跳蚤市场
    <QQ_GROUP_ID>,   # 榴园闲聊互助群
    <QQ_GROUP_ID>,   # 没钱快冲薅羊毛
    <QQ_GROUP_ID>,   # 安徽大学二手交易9群
    <QQ_GROUP_ID>,   # 安徽大学闲置物品群
    <QQ_GROUP_ID>,   # 西电二手群1
    <QQ_GROUP_ID>,   # 西电杭州研究院聊天群
]

MAX_MESSAGES_PER_GROUP = 5000
DAYS_BACK = 14

# 是否下载图片
DOWNLOAD_IMAGES = True

# ============ 存储结构 ============
# messages/
# ├── raw/           原始数据（API完整返回，不修改）
# │   └── raw_20260701_153000.jsonl
# ├── processed/     筛选后数据（分类+图片路径）
# │   └── processed_20260701_153000.jsonl
# ├── images/        下载的图片
# │   └── {group_id}/
# │       └── {timestamp}_{seq}.jpg
# └── stats_*.json  统计

BASE_DIR = "messages"
RAW_DIR = os.path.join(BASE_DIR, "raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
IMAGES_DIR = os.path.join(BASE_DIR, "images")

timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
RAW_FILE = os.path.join(RAW_DIR, f"raw_{timestamp_str}.jsonl")
PROCESSED_FILE = os.path.join(PROCESSED_DIR, f"processed_{timestamp_str}.jsonl")
STATS_FILE = os.path.join(BASE_DIR, f"stats_{timestamp_str}.json")

# ================================


def call_api(action, **params):
    url = f"{NAPCAT_HTTP_URL}/{action}"
    headers = {}
    if ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    try:
        resp = requests.post(url, json=params, headers=headers, timeout=15)
        result = resp.json()
        if result.get("retcode") != 0:
            print(f"  API错误: {result.get('retmsg', '未知')}")
            return None
        return result.get("data")
    except requests.exceptions.ConnectionError:
        print(f"\n[错误] 无法连接 {NAPCAT_HTTP_URL}")
        print("请在NapCat WebUI中添加并启用HTTP服务端（端口3000）")
        return None
    except Exception as e:
        print(f"\n[错误] {e}")
        return None


def get_group_list():
    data = call_api("get_group_list")
    return data if data else []


def get_group_msg_history(group_id, message_seq=None, count=50):
    """
    拉取群历史消息。
    message_seq: 翻页游标（上一批最早消息的message_id），None=获取最新消息
    count: 每次拉取数量（默认50，减少API调用次数）
    reverse_order: True=从新到旧排列（翻页拉取历史必须设为true）
    """
    params = {
        "group_id": str(group_id),
        "count": count,
        "reverse_order": True,  # 关键：获取历史消息的正确方向
    }
    if message_seq is not None:
        params["message_seq"] = str(message_seq)
    return call_api("get_group_msg_history", **params)


def extract_image_urls(message_data):
    """从消息段中提取所有图片URL"""
    urls = []
    if isinstance(message_data, list):
        for seg in message_data:
            if isinstance(seg, dict) and seg.get("type") == "image":
                data = seg.get("data", {})
                url = data.get("url") or data.get("file_url", "")
                if url:
                    urls.append(url)
    return urls


def extract_text(message_data):
    """提取纯文本，图片用[图片]占位"""
    if isinstance(message_data, str):
        return message_data
    if isinstance(message_data, list):
        texts = []
        for seg in message_data:
            if isinstance(seg, dict):
                t = seg.get("type", "")
                if t == "text":
                    texts.append(seg.get("data", {}).get("text", ""))
                elif t == "image":
                    texts.append("[图片]")
                elif t == "face":
                    texts.append("[表情]")
                elif t == "at":
                    texts.append("[@]")
                else:
                    texts.append(f"[{t}]")
        return "".join(texts).strip()
    return str(message_data)


def classify(text):
    sell_kw = ["出", "出售", "转让", "闲置", "卖", "清", "免费送", "低价"]
    buy_kw = ["求", "求购", "收", "想要", "需要", "找"]
    notice_kw = ["通知", "公告", "请同学", "安排", "报名", "截止", "ddl", "DDL"]
    for kw in sell_kw:
        if kw in text:
            return "sell"
    for kw in buy_kw:
        if kw in text:
            return "buy"
    for kw in notice_kw:
        if kw in text:
            return "notice"
    return "chat"


def download_image(url, save_path):
    """下载图片到本地"""
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        pass
    return False


def process_msg(msg, group_id, group_name, download_imgs=True):
    """处理单条消息：返回 (raw_msg, processed_msg)"""
    try:
        sender = msg.get("sender", {})
        message_content = msg.get("message", "")
        msg_time = msg.get("time", 0)
        msg_id = msg.get("message_id", "")
        msg_seq = msg.get("message_seq", "")
        
        # 提取文本
        text = extract_text(message_content)
        
        # 提取图片URL
        image_urls = extract_image_urls(message_content)
        
        # 如果既没文本也没图片，跳过
        if not text and not image_urls:
            return None, None
        
        time_str = datetime.fromtimestamp(msg_time).strftime("%Y-%m-%d %H:%M:%S") if msg_time else ""
        
        # 下载图片
        local_images = []
        if download_imgs and image_urls:
            for i, url in enumerate(image_urls):
                ext = ".jpg"
                if ".png" in url:
                    ext = ".png"
                img_name = f"{msg_time}_{msg_seq}_{i}{ext}" if msg_seq else f"{msg_time}_{msg_id}_{i}{ext}"
                img_path = os.path.join(IMAGES_DIR, str(group_id), img_name)
                if download_image(url, img_path):
                    local_images.append(os.path.join("images", str(group_id), img_name))
        
        # 是否纯图片消息
        is_image_only = bool(image_urls) and not text.strip()
        
        category = classify(text) if text else "image"
        
        # 构建原始数据（完整保留API返回）
        raw_record = {
            "message_id": msg_id,
            "message_seq": msg_seq,
            "time": msg_time,
            "group_id": group_id,
            "group_name": group_name,
            "user_id": msg.get("user_id", 0),
            "sender": sender,
            "message": message_content,
            "raw_message": msg.get("raw_message", ""),
        }
        
        # 构建筛选后数据
        processed_record = {
            "message_id": msg_id,
            "message_seq": msg_seq,
            "time": msg_time,
            "time_str": time_str,
            "group_id": group_id,
            "group_name": group_name,
            "user_id": msg.get("user_id", 0),
            "nickname": sender.get("nickname", ""),
            "card": sender.get("card", ""),
            "text": text,
            "category": category,
            "has_image": bool(image_urls),
            "image_count": len(image_urls),
            "image_urls": image_urls,
            "local_images": local_images,
            "is_image_only": is_image_only,
        }
        
        return raw_record, processed_record
    except Exception as e:
        return None, None


def fetch_group(group_id, group_name, max_count, min_timestamp):
    """拉取一个群的历史消息"""
    print(f"\n拉取 [{group_name}]({group_id}) ...")
    
    raw_msgs = []
    processed_msgs = []
    message_seq = None
    batch = 0
    stop = False
    img_downloaded = 0
    seen_ids = set()  # 去重：记录已处理的消息ID

    while len(processed_msgs) < max_count and not stop:
        batch += 1
        data = get_group_msg_history(group_id, message_seq, count=50)

        if data is None:
            print(f"  第{batch}批: API返回空，停止")
            break

        messages = data.get("messages", [])
        if not messages:
            print(f"  第{batch}批: 没有更多消息，停止")
            break

        # 去重：过滤掉已处理的消息
        new_messages = []
        for msg in messages:
            mid = msg.get("message_id", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                new_messages.append(msg)
            elif not mid:
                new_messages.append(msg)

        if not new_messages:
            print(f"  第{batch}批: {len(messages)}条全部重复，没有更多历史消息，停止")
            break

        for msg in new_messages:
            raw, processed = process_msg(msg, group_id, group_name, DOWNLOAD_IMAGES)
            if raw and processed:
                # 时间过滤
                if min_timestamp and processed["time"] > 0 and processed["time"] < min_timestamp:
                    stop = True
                    continue
                raw_msgs.append(raw)
                processed_msgs.append(processed)
                img_downloaded += processed["image_count"]

        # 进度显示
        last_time = new_messages[-1].get("time", 0) if new_messages else 0
        time_info = ""
        if last_time:
            time_info = f"（到 {datetime.fromtimestamp(last_time).strftime('%m-%d %H:%M')}）"
        print(f"  第{batch}批: {len(new_messages)}条新, 累计{len(processed_msgs)}条, 图片{img_downloaded}张 {time_info}")

        # 翻页：取本批最早（时间最小）消息的message_id作为下一次游标
        if new_messages:
            earliest = min(new_messages, key=lambda m: m.get("time", 0))
            next_seq = str(earliest.get("message_id", ""))
            
            # 防止无限循环：如果游标没变，说明没有更多历史消息
            if not next_seq or next_seq == str(message_seq):
                print(f"  游标未变化，没有更多历史消息，停止")
                break
            message_seq = next_seq
        else:
            break

        if stop:
            print(f"  已达到{DAYS_BACK}天前，停止")
            break

        time.sleep(0.2)

    # 去重
    seen = set()
    raw_unique = []
    processed_unique = []
    for r, p in zip(raw_msgs, processed_msgs):
        mid = r["message_id"]
        if mid and mid not in seen:
            seen.add(mid)
            raw_unique.append(r)
            processed_unique.append(p)
        elif not mid:
            raw_unique.append(r)
            processed_unique.append(p)

    print(f"  完成: {len(processed_unique)}条消息, {img_downloaded}张图片（去重后）")
    return raw_unique, processed_unique


def save_jsonl(messages, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"  已保存 {len(messages)} 条到: {filename}")


def print_summary(messages):
    if not messages:
        return
    print(f"\n{'='*60}")
    print(f"  统计摘要")
    print(f"{'='*60}")

    gs = {}
    total_images = 0
    for m in messages:
        gid = m["group_id"]
        if gid not in gs:
            gs[gid] = {"name": m["group_name"], "total": 0, "sell": 0, "buy": 0, "chat": 0, "notice": 0, "image": 0, "imgs": 0}
        gs[gid]["total"] += 1
        gs[gid][m["category"]] += 1
        if m["has_image"]:
            total_images += m["image_count"]
            gs[gid]["imgs"] += m["image_count"]

    for gid, s in gs.items():
        print(f"\n  [{s['name']}]({gid})")
        print(f"    总: {s['total']}  出售: {s['sell']}  求购: {s['buy']}  通知: {s['notice']}  闲聊: {s['chat']}  纯图: {s['image']}  图片: {s['imgs']}张")

    times = [m["time"] for m in messages if m["time"] > 0]
    if times:
        print(f"\n  时间: {datetime.fromtimestamp(min(times)).strftime('%Y-%m-%d %H:%M')} ~ {datetime.fromtimestamp(max(times)).strftime('%Y-%m-%d %H:%M')}")
    print(f"\n  总消息: {len(messages)} 条")
    print(f"  总图片: {total_images} 张")
    print(f"{'='*60}")


def main():
    print("="*60)
    print(f"  QQ群历史消息拉取工具 v3")
    print(f"  时间范围: 最近 {DAYS_BACK} 天")
    print(f"  下载图片: {'是' if DOWNLOAD_IMAGES else '否'}")
    print(f"  原始数据: {RAW_FILE}")
    print(f"  筛选数据: {PROCESSED_FILE}")
    print("="*60)

    # 时间过滤
    min_ts = 0
    if DAYS_BACK:
        cutoff = datetime.now() - timedelta(days=DAYS_BACK)
        min_ts = int(cutoff.timestamp())
        print(f"  只保留 {cutoff.strftime('%Y-%m-%d')} 之后的消息")

    # 交互选群
    if not GROUPS_TO_FETCH:
        print("\n获取群列表...")
        groups = get_group_list()
        if not groups:
            print("获取失败，请检查HTTP服务端（端口3000）")
            return

        print(f"\n你加入了 {len(groups)} 个群：")
        for i, g in enumerate(groups):
            print(f"  {i+1}. [{g['group_name']}] ({g['group_id']})")

        print(f"\n输入序号（逗号分隔，支持中英文逗号），或 all：")
        choice = input("> ").strip()

        if choice.lower() == "all":
            GROUPS_TO_FETCH.extend([g["group_id"] for g in groups])
        else:
            for part in choice.replace("，", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(groups):
                        GROUPS_TO_FETCH.append(groups[idx]["group_id"])
                except ValueError:
                    print(f"  忽略无效输入: {part}")

        if not GROUPS_TO_FETCH:
            print("未选择任何群")
            return

    print(f"\n将拉取 {len(GROUPS_TO_FETCH)} 个群...")

    # 群名映射
    group_names = {}
    groups = get_group_list()
    for g in groups:
        group_names[g["group_id"]] = g["group_name"]

    all_raw = []
    all_processed = []
    for gid in GROUPS_TO_FETCH:
        name = group_names.get(gid, str(gid))
        raw, processed = fetch_group(gid, name, MAX_MESSAGES_PER_GROUP, min_ts)
        all_raw.extend(raw)
        all_processed.extend(processed)

    if not all_processed:
        print("\n未获取到任何消息")
        return

    # 保存原始数据
    print(f"\n--- 保存数据 ---")
    save_jsonl(all_raw, RAW_FILE)
    
    # 保存筛选后数据
    save_jsonl(all_processed, PROCESSED_FILE)

    # 统计
    print_summary(all_processed)

    print(f"\n--- 文件说明 ---")
    print(f"  原始数据（API完整返回）: {RAW_FILE}")
    print(f"  筛选数据（分类+图片路径）: {PROCESSED_FILE}")
    print(f"  图片目录: {IMAGES_DIR}/")
    print(f"\n下一步: 用 {PROCESSED_FILE} 标注并训练BERT模型")


if __name__ == "__main__":
    main()
