"""
数据预处理工具 v2
功能：
  1. 读取拉取的 raw JSONL（原始数据，含完整消息段）
  2. 表情包过滤（sub_type + summary + 文件大小三重判断）
  3. 同一用户短时间内的消息自动合并
  4. 多商品消息拆分（文字和图片交替时，拆成独立商品）
  5. 对图片消息做OCR提取文字
  6. 统一分类意图
  7. 输出标注友好的格式 + HTML预览

使用前：
  1. 安装OCR依赖：pip install paddlepaddle paddleocr
     （如果paddlepaddle装不上，脚本会自动降级为仅处理文字）
  2. 运行：python preprocess.py
"""

import os
# 设置离线模式，避免sentence-transformers的httpx client关闭问题
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import json
import re
import hashlib
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ============ 配置区 ============

# 输入：从 raw 目录读取原始数据（含完整消息段，能区分表情包）
INPUT_DIR = "messages/raw"
INPUT_FILE = None  # None=自动找最新的

# 输出目录
OUTPUT_DIR = "messages/labeled"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "ready_to_label.jsonl")
REVIEW_HTML = os.path.join(OUTPUT_DIR, "review.html")

# 合并窗口：同一用户在N秒内发的消息视为一组
MERGE_TIME_WINDOW = 60  # 秒

# 图片目录
IMAGES_BASE = "messages/images"

# 表情包过滤配置
STICKER_SUB_TYPES = {1}           # sub_type=1 是表情包
STICKER_MIN_FILE_SIZE = 10240     # <10KB的图片大概率是表情包
STICKER_SUMMARY_PATTERNS = [       # summary匹配这些的是表情包
    "[动画表情]", "[动画表情]", "[表情]",
]

# 合并条数上限：同一用户超过此条数不再合并（防止批量转发被误合并）
MAX_MERGE_COUNT = 10

# 短文字判断：拆分多商品时，短于此长度且不含交易/价格关键词的文字视为补充描述
SUPPLEMENT_TEXT_MAX_LEN = 10
SUPPLEMENT_KEYWORDS = ["r", "R", "块", "元", "米", "¥", "￥", "出", "收", "求", "卖"]

# ================================

SELL_KEYWORDS = ["出", "出售", "转让", "闲置", "卖", "清", "免费送", "低价", "低价出", "处理", "退坑", "半价", "打折", "出租", "转租", "合租", "月租", "租金", "找房", "直租", "送", "来拿", "自提", "自取", "有要的"]
BUY_KEYWORDS = ["求", "求购", "收", "想要", "需要", "找", "求收", "高价收", "求租", "租", "租用", "短期租", "求房", "蹲", "有偿借用", "代课", "借用", "借", "还在吗", "求借"]
NOTICE_KEYWORDS = ["通知", "公告", "请同学", "安排", "报名", "截止", "ddl", "DDL", "作业", "提交"]

ITEM_KEYWORDS = [
    "电动车", "自行车", "电瓶车", "小电驴",
    "教材", "课本", "书", "高数", "线代", "概率论", "英语",
    "电脑", "笔记本", "平板", "ipad", "显示器", "键盘", "鼠标",
    "手机", "充电器", "耳机", "音箱",
    "桌子", "椅子", "柜子", "床", "床垫",
    "风扇", "空调", "台灯", "灯",
    "衣服", "鞋", "包",
    "锅", "碗", "水壶", "热水壶",
    "会员", "vip", "网课",
    "路由器", "插座", "数据线",
    "吉他", "尤克里里", "乐器",
    "考研", "考公", "资料", "笔记",
]

PRICE_KEYWORDS = ["块", "元", "r", "R", "¥", "￥", "米", "毛"]

# 同义词映射表：搜索时自动扩展
# 搜左边的词时，右边的同义词也会一起搜
SYNONYM_MAP = {
    "自行车": ["山地车", "公路车", "单车", "脚踏车", "共享单车"],
    "电动车": ["电瓶车", "小电驴", "电驴", "电摩托", "电瓶"],
    "教材": ["课本", "书", "课本书", "教材书", "教科书"],
    "电脑": ["笔记本", "笔记本电脑", "本本", "手提", "轻薄本", "游戏本"],
    "平板": ["ipad", "iPad", "pad", "平板电脑", "matepad"],
    "手机": ["phone", "iPhone", "华为", "小米", "OPPO", "vivo", "荣耀"],
    "显示器": ["屏幕", "显示屏", "monitor"],
    "键盘": ["机械键盘", "薄膜键盘", "keychron", "罗技"],
    "鼠标": ["mouse", "罗技", "雷蛇"],
    "耳机": ["earbuds", "蓝牙耳机", "头戴式", "入耳式", "airpods"],
    "桌子": ["书桌", "电脑桌", "餐桌", "学习桌", "折叠桌"],
    "椅子": ["凳子", "座椅", "办公椅", "电竞椅", "学习椅"],
    "床": ["床垫", "床铺", "上下铺", "单人床", "双人床"],
    "风扇": ["电风扇", "台扇", "落地扇", "小风扇", "usb风扇"],
    "台灯": ["灯", " desk lamp", "护眼灯", "床头灯"],
    "水壶": ["热水壶", "电水壶", "烧水壶", "保温壶"],
    "衣服": ["外套", "卫衣", "裤子", "T恤", "衬衫", "羽绒服", "上衣"],
    "鞋": ["鞋子", "球鞋", "运动鞋", "板鞋", "aj", "nike", "阿迪"],
    "包": ["书包", "双肩包", "单肩包", "托特包", "斜挎包"],
    "会员": ["vip", "VIP", "svip", "超级会员", "年费", "月卡"],
    "网课": ["课程", "网课", "慕课", "mooc", "视频课"],
    "考研": ["考研资料", "考研书", "考研笔记", "政治", "英语", "数学"],
    "充电器": ["电源", "适配器", "充电头", "快充", "充电线"],
    "路由器": ["wifi", "无线", "交换机", "网线"],
    "吉他": ["尤克里里", "乐器", "电子琴", "钢琴", "口琴"],
    "锅": ["电饭锅", "电饭煲", "炒锅", "煮锅", "电磁炉"],
    "柜子": ["收纳柜", "衣柜", "书架", "置物架", "储物柜"],
}


def classify_intent(text, has_image=False):
    if not text:
        return "pending_ocr" if has_image else "chat"
    # "送"需要特殊处理：排除"送到""送不""送水""派送""起送"等非出售语境
    import re
    has_sell_song = bool(re.search(r'(?<![派起运配递客投])送(?!到|不|水|货|餐)', text))
    
    for kw in SELL_KEYWORDS:
        if kw == "送":
            if has_sell_song:
                return "sell"
        elif kw in text:
            return "sell"
    for kw in BUY_KEYWORDS:
        if kw in text:
            return "buy"
    for kw in NOTICE_KEYWORDS:
        if kw in text:
            return "notice"
    has_price = any(kw in text for kw in PRICE_KEYWORDS)
    has_item = any(kw in text for kw in ITEM_KEYWORDS)
    # 有价格就大概率是出售（即使没有物品名，如"5r"+图片）
    if has_price:
        return "sell"
    # 有图片但没文字内容，等待OCR
    if has_image and not has_item:
        return "pending_ocr"
    return "chat"


def extract_entities_simple(text):
    if not text:
        return {"items": [], "prices": [], "conditions": []}
    items = [kw for kw in ITEM_KEYWORDS if kw in text]
    prices = []
    for pattern in [r'(\d+(?:\.\d+)?)\s*(块|元|r|R|米|¥|￥)', r'(¥|￥)\s*(\d+(?:\.\d+)?)']:
        prices.extend(["".join(m) if isinstance(m, tuple) else m for m in re.findall(pattern, text)])
    conditions = [kw for kw in ["全新", "未拆封", "九成新", "9成新", "八成新", "8成新", "七成新", "7成新", "几乎全新", "成色好"] if kw in text]
    return {"items": items, "prices": prices, "conditions": conditions}


# ============ 联系方式提取 ============

def extract_contact_info(text):
    """
    从文本中提取联系方式：QQ号、微信号、手机号
    返回 {"qq": "", "wechat": "", "phone": "", "raw": "原始匹配文本"}
    """
    if not text:
        return {"qq": "", "wechat": "", "phone": ""}
    
    result = {"qq": "", "wechat": "", "phone": ""}
    
    # QQ号：关键词 + 5-12位数字
    qq_patterns = [
        r'[Qq][Qq][:：]?\s*(\d{5,12})',
        r'[Qq][Qq]号[:：]?\s*(\d{5,12})',
        r'扣[:：]?\s*(\d{5,12})',
        r'扣号[:：]?\s*(\d{5,12})',
        r'加\s*[Qq]{2}\s*(\d{5,12})',
    ]
    for pattern in qq_patterns:
        m = re.search(pattern, text)
        if m:
            result["qq"] = m.group(1)
            break
    
    # 微信号：关键词 + 字母数字组合（6-20位）
    wechat_patterns = [
        r'[Vv]x[:：]?\s*([A-Za-z0-9_-]{6,20})',
        r'[Vv]信[:：]?\s*([A-Za-z0-9_-]{6,20})',
        r'微信[:：]?\s*([A-Za-z0-9_-]{6,20})',
        r'加[Vv]\s*([A-Za-z0-9_-]{6,20})',
        r'加微\s*([A-Za-z0-9_-]{6,20})',
    ]
    for pattern in wechat_patterns:
        m = re.search(pattern, text)
        if m:
            result["wechat"] = m.group(1)
            break
    
    # 手机号：1开头11位数字，需排除价格中的数字
    # 先把价格数字（如 30r, 20块, ¥50）替换掉，避免误匹配
    text_no_price = re.sub(r'\d+(?:\.\d+)?\s*(?:r|R|块|元|米|毛|¥|￥)', '', text)
    phone_match = re.search(r'(?<!\d)(1[3-9]\d{9})(?!\d)', text_no_price)
    if phone_match:
        result["phone"] = phone_match.group(1)
    
    return result


# ============ 表情包过滤 ============

def is_sticker(image_seg_data):
    """
    判断一个图片消息段是否是表情包
    三重判断：sub_type + summary + file_size
    """
    if not isinstance(image_seg_data, dict):
        return False
    
    # 判断1：sub_type
    sub_type = image_seg_data.get("sub_type", 0)
    try:
        sub_type = int(sub_type)
    except:
        sub_type = 0
    if sub_type in STICKER_SUB_TYPES:
        return True
    
    # 判断2：summary 包含表情包标识
    summary = image_seg_data.get("summary", "")
    if summary:
        for pattern in STICKER_SUMMARY_PATTERNS:
            if pattern in summary:
                return True
        # summary是单个[字]的，可能是QQ内置表情
        if re.match(r'^\[.{1,4}\]$', summary) and "动画表情" not in summary:
            return True
    
    # 判断3：文件大小过小
    file_size = image_seg_data.get("file_size", "0")
    try:
        file_size = int(file_size)
    except:
        file_size = 0
    if 0 < file_size < STICKER_MIN_FILE_SIZE:
        return True
    
    return False


def filter_stickers_from_message(message_segments):
    """
    从消息段列表中过滤掉表情包，返回 (非表情包段, 被过滤数量)
    """
    filtered = []
    sticker_count = 0
    for seg in message_segments:
        if isinstance(seg, dict):
            if seg.get("type") == "image":
                data = seg.get("data", {})
                if is_sticker(data):
                    sticker_count += 1
                    continue  # 跳过表情包
        filtered.append(seg)
    return filtered, sticker_count


# ============ 多商品消息拆分 ============

def split_multi_item_message(message_segments):
    """
    将一条含多个商品的消息拆分成多条。
    
    核心原则：图片归属于它前面的文字描述（用户习惯：先打字描述，再发图）
    - 两段文字之间的图片 → 归前一段文字
    - 最后一段文字之后的图片 → 归最后一段文字
    - 第一段文字之前的图片 → 归第一段文字
    
    例如：[文1][图A][文2][图B][图C][文3][图D]
    →  item1: 文1 + 图A
    →  item2: 文2 + 图B + 图C
    →  item3: 文3 + 图D
    
    再例如：[图][文1][图A][文2][图B]
    →  item1: 图 + 文1 + 图A  （开头的图归第一段文字）
    →  item2: 文2 + 图B
    """
    if not isinstance(message_segments, list):
        return [message_segments]
    
    # 找出所有文字段的位置
    text_positions = []
    for i, seg in enumerate(message_segments):
        if isinstance(seg, dict) and seg.get("type") == "text":
            text = seg.get("data", {}).get("text", "").strip()
            if text:
                text_positions.append(i)
    
    # 如果没有文字，或只有一个文字段，不需要拆分
    if len(text_positions) <= 1:
        return [message_segments]
    
    # 判断哪些文字段是"补充描述"而非新商品：
    # 条件：短文字(<=SUPPLEMENT_TEXT_MAX_LEN) 且 不含交易/价格关键词
    # 这些文字不作为分割点，而是连同后面的图片归到前一个商品
    is_supplement = []
    for tp in text_positions:
        text = message_segments[tp].get("data", {}).get("text", "").strip()
        if len(text) <= SUPPLEMENT_TEXT_MAX_LEN:
            has_kw = any(kw in text for kw in SUPPLEMENT_KEYWORDS)
            if not has_kw:
                is_supplement.append(True)
                continue
        is_supplement.append(False)
    
    # 筛选：只有非补充描述的文字段才作为分割点
    # 第一段文字总是分割点（不管长短）
    split_positions = []
    for i, tp in enumerate(text_positions):
        if i == 0 or not is_supplement[i]:
            split_positions.append(tp)
    
    # 如果筛选后只剩1个分割点，不需要拆分
    if len(split_positions) <= 1:
        return [message_segments]
    
    # 按筛选后的分割点分组：图片归前面的文字
    items = []
    prev_pos = 0
    pre_text_segments = []  # 第一段文字之前的段（归第一组）
    
    for tp in split_positions:
        # 当前分割点与上一个分割点之间的段（含补充描述文字）
        between = list(message_segments[prev_pos:tp])
        if items:
            # 归到前一个分组（图片跟着前面的文字）
            items[-1].extend(between)
        else:
            # 第一段文字之前的段，暂存
            pre_text_segments = between
        # 新建一个分组，以文字开头
        items.append([message_segments[tp]])
        prev_pos = tp + 1
    
    # 最后一个分割点之后的段，归最后一组
    if prev_pos < len(message_segments):
        remaining = list(message_segments[prev_pos:])
        if items:
            items[-1].extend(remaining)
        else:
            items.append(remaining)
    
    # 第一段文字之前的段，合并到第一组
    if pre_text_segments and items:
        items[0] = pre_text_segments + items[0]
    
    # 合并空分组
    items = [g for g in items if g]
    
    # 如果拆分后只有1组，不拆分
    if len(items) <= 1:
        return [message_segments]
    
    return items


# ============ 消息处理 ============

def extract_text_from_segments(segments):
    texts = []
    for seg in segments:
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


def extract_image_info(segments):
    """从消息段中提取图片信息（URL和已下载的本地路径）"""
    images = []
    for seg in segments:
        if isinstance(seg, dict) and seg.get("type") == "image":
            data = seg.get("data", {})
            url = data.get("url", "")
            file_size = 0
            try:
                file_size = int(data.get("file_size", "0"))
            except:
                pass
            sub_type = data.get("sub_type", 0)
            images.append({
                "url": url,
                "file_size": file_size,
                "sub_type": sub_type,
                "summary": data.get("summary", ""),
            })
    return images


def load_messages(filepath):
    messages = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except:
                    pass
    return messages


def find_local_images_for_merged(group_id, message_seqs):
    """
    为合并消息查找所有本地图片。
    文件名格式: {time}_{message_seq}_{img_index}.jpg
    核心策略：按 message_seq 匹配，不依赖 time（合并后time可能不对）
    """
    img_dir = os.path.join(IMAGES_BASE, str(group_id))
    if not os.path.exists(img_dir):
        return []
    
    seq_strs = [str(s) for s in message_seqs if s]
    matched = []
    for fname in os.listdir(img_dir):
        # 文件名格式: 1781698969_1773586801_0.jpg
        # 按 _ 分割，第二段是 message_seq
        parts = fname.rsplit(".", 1)[0].split("_")
        if len(parts) >= 2:
            file_seq = parts[1]
            if file_seq in seq_strs:
                rel_path = os.path.join("images", str(group_id), fname)
                if rel_path not in matched:
                    matched.append(rel_path)
    
    # 按文件名排序（保持时间顺序）
    matched.sort()
    return matched


def merge_messages(messages, time_window):
    """合并同一用户在time_window秒内的消息"""
    if not messages:
        return []
    
    by_group = defaultdict(list)
    for msg in messages:
        by_group[msg.get("group_id", 0)].append(msg)
    
    merged_all = []
    
    for group_id, group_msgs in by_group.items():
        group_msgs.sort(key=lambda x: x.get("time", 0))
        
        merged = []
        current = None
        
        for msg in group_msgs:
            msg_time = msg.get("time", 0)
            msg_user = msg.get("user_id", 0)
            message_content = msg.get("message", [])
            
            if current is None:
                current = create_merged(msg)
                continue
            
            if (msg_user == current["user_id"] and 
                msg_time - current["last_time"] <= time_window and
                msg_time - current["last_time"] >= 0 and
                current["msg_count"] < MAX_MERGE_COUNT):
                merge_into(current, msg)
            else:
                merged.append(finalize_merged(current))
                current = create_merged(msg)
        
        if current:
            merged.append(finalize_merged(current))
        
        merged_all.extend(merged)
    
    merged_all.sort(key=lambda x: x.get("first_time", 0))
    return merged_all


def create_merged(msg):
    segments = msg.get("message", [])
    # 过滤表情包
    filtered_segments, sticker_count = filter_stickers_from_message(segments)
    
    text_parts = []
    for seg in filtered_segments:
        if isinstance(seg, dict) and seg.get("type") == "text":
            t = seg.get("data", {}).get("text", "").strip()
            if t:
                text_parts.append(t)
    
    images = extract_image_info(filtered_segments)
    
    return {
        "message_ids": [msg.get("message_id", "")],
        "message_seqs": [msg.get("message_seq", "")],
        "first_time": msg.get("time", 0),
        "last_time": msg.get("time", 0),
        "group_id": msg.get("group_id"),
        "group_name": msg.get("group_name", ""),
        "user_id": msg.get("user_id", 0),
        "nickname": msg.get("sender", {}).get("nickname", ""),
        "card": msg.get("sender", {}).get("card", ""),
        "all_segments": list(filtered_segments),  # 保存过滤后的所有段
        "text_parts": text_parts,
        "combined_text": " ".join(text_parts) if text_parts else "",
        "image_infos": images,
        "image_paths": [],
        "filtered_stickers": sticker_count,
        "msg_count": 1,
    }


def merge_into(current, msg):
    segments = msg.get("message", [])
    filtered_segments, sticker_count = filter_stickers_from_message(segments)
    
    current["message_ids"].append(msg.get("message_id", ""))
    current["message_seqs"].append(msg.get("message_seq", ""))
    current["last_time"] = msg.get("time", 0)
    current["msg_count"] += 1
    current["filtered_stickers"] += sticker_count
    
    for seg in filtered_segments:
        current["all_segments"].append(seg)
        if isinstance(seg, dict) and seg.get("type") == "text":
            t = seg.get("data", {}).get("text", "").strip()
            if t:
                current["text_parts"].append(t)
                current["combined_text"] = " ".join(current["text_parts"])
    
    images = extract_image_info(filtered_segments)
    current["image_infos"].extend(images)


def finalize_merged(current):
    # 先判断分类
    all_text = current["combined_text"]
    current["full_text"] = all_text.strip()
    current["category"] = classify_intent(all_text, current.get("has_image", False))
    
    # 如果关键词分类为chat，尝试kNN分类（临时禁用，太慢）
    # if current["category"] == "chat":
    #     try:
    #         from knn_classifier import classify_with_knn
    #         knn_cat = classify_with_knn(all_text, current.get("has_image", False))
    #         if knn_cat != "chat":
    #             current["category"] = knn_cat
    #             current["_knn_classified"] = True  # 标记kNN修改的分类
    #     except:
    #         pass  # kNN不可用时回退到纯关键词
    
    current["entities"] = extract_entities_simple(all_text)
    current["contact_info"] = extract_contact_info(all_text)
    
    # 只对交易类消息（出售/求购）尝试多商品拆分
    # 闲聊/通知/待OCR不拆分，避免误拆
    if current["category"] in ("sell", "buy"):
        split_items = split_multi_item_message(current["all_segments"])
    else:
        split_items = []
    
    if len(split_items) > 1:
        # 多商品：拆分成多条
        current["is_multi_item"] = True
        current["split_items"] = []
        for i, item_segments in enumerate(split_items):
            item_text = extract_text_from_segments([s for s in item_segments if isinstance(s, dict) and s.get("type") == "text"])
            item_images = extract_image_info(item_segments)
            item_data = {
                "item_index": i,
                "text": item_text,
                "image_count": len(item_images),
                "images": item_images,
            }
            current["split_items"].append(item_data)
    else:
        current["is_multi_item"] = False
        current["split_items"] = []
    
    # 多商品拆分后，每个子商品也提取联系方式
    if current.get("is_multi_item") and current.get("split_items"):
        for item in current["split_items"]:
            item["contact_info"] = extract_contact_info(item.get("text", ""))
    
    # 图片信息
    current["image_count"] = len(current["image_infos"])
    current["has_image"] = current["image_count"] > 0
    current["is_image_only"] = current["has_image"] and not current["combined_text"].strip()
    current["is_empty"] = not current["has_image"] and not current["combined_text"].strip()
    
    if current["first_time"]:
        current["time_str"] = datetime.fromtimestamp(current["first_time"]).strftime("%Y-%m-%d %H:%M:%S")
    else:
        current["time_str"] = ""
    
    # 查找本地图片路径（按 message_seq 批量匹配）
    current["image_paths"] = find_local_images_for_merged(current["group_id"], current["message_seqs"])
    
    return current


# ============ OCR ============

_ocr_engine = None

def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    try:
        import easyocr
        _ocr_engine = easyocr.Reader(['ch_sim', 'en'], gpu=False)
        print("  [OCR] EasyOCR 加载成功")
        return _ocr_engine
    except ImportError:
        print("  [OCR] EasyOCR 未安装，跳过图片OCR")
        print("  [OCR] 安装: pip install easyocr")
        _ocr_engine = False
        return False
    except Exception as e:
        print(f"  [OCR] 加载失败: {e}")
        _ocr_engine = False
        return False


def ocr_image(image_path, cache=None):
    engine = get_ocr_engine()
    if engine is False:
        return ""
    
    # 检查缓存
    if cache is not None and image_path in cache:
        return cache[image_path]
    
    full_path = os.path.join("messages", image_path) if not os.path.isabs(image_path) else image_path
    if not os.path.exists(full_path):
        return ""
    try:
        # 用PIL读取图片（支持MPO等特殊格式），转为numpy数组
        from PIL import Image
        import numpy as _np
        pil_img = Image.open(full_path).convert('RGB')
        
        # 缩小图片到最大800px宽，OCR不需要高清图，大幅加速
        max_width = 800
        if pil_img.width > max_width:
            ratio = max_width / pil_img.width
            new_size = (max_width, int(pil_img.height * ratio))
            pil_img = pil_img.resize(new_size, Image.LANCZOS)
        
        img_array = _np.array(pil_img)
        
        # EasyOCR识别
        result = engine.readtext(img_array)
        if not result:
            return ""
        texts = []
        for item in result:
            if item and len(item) >= 2:
                text = item[1]
                if text and text.strip():
                    texts.append(text.strip())
        result_text = " ".join(texts)
        # 写入缓存
        if cache is not None:
            cache[image_path] = result_text
        return result_text
    except:
        return ""


def load_ocr_cache():
    """加载OCR缓存文件"""
    cache_path = os.path.join(OUTPUT_DIR, "ocr_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_ocr_cache(cache):
    """保存OCR缓存"""
    cache_path = os.path.join(OUTPUT_DIR, "ocr_cache.json")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# 已确认OCR的文件路径
CONFIRMED_OCR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages", "labeled", "confirmed_ocr.json")

def load_confirmed_ocr():
    """加载已确认的OCR消息 {msg_id: cat}"""
    if os.path.exists(CONFIRMED_OCR_FILE):
        try:
            with open(CONFIRMED_OCR_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # 格式: ["msg_id:cat", ...]
                    result = {}
                    for entry in data:
                        if ":" in entry:
                            mid, cat = entry.rsplit(":", 1)
                            result[mid] = cat
                    return result
                elif isinstance(data, dict):
                    return data
        except:
            pass
    return {}

def save_confirmed_ocr(confirmed_set):
    """保存已确认的OCR消息ID集合"""
    os.makedirs(os.path.dirname(CONFIRMED_OCR_FILE), exist_ok=True)
    with open(CONFIRMED_OCR_FILE, "w", encoding="utf-8") as f:
        json.dump(list(confirmed_set), f, ensure_ascii=False)


def run_ocr(merged_messages):
    img_count = sum(m["image_count"] for m in merged_messages if m.get("has_image"))
    if img_count == 0:
        print("  没有图片需要OCR")
        return
    
    print(f"  共 {img_count} 张图片需要OCR...")
    engine = get_ocr_engine()
    if engine is False:
        return
    
    # 加载缓存
    ocr_cache = load_ocr_cache()
    cached_count = 0
    new_count = 0
    
    # 加载已确认的OCR {msg_id: cat}
    confirmed = load_confirmed_ocr()
    
    ocr_success = 0
    processed = 0
    for i, msg in enumerate(merged_messages):
        if not msg.get("image_paths"):
            continue
        
        ocr_texts = []
        for img_path in msg["image_paths"]:
            if img_path in ocr_cache:
                cached_count += 1
                text = ocr_cache[img_path]
            else:
                text = ocr_image(img_path, ocr_cache)
                new_count += 1
            if text:
                ocr_texts.append(text)
                ocr_success += 1
            processed += 1
        
        msg["ocr_texts"] = ocr_texts
        
        # OCR提取到文字后的分类逻辑
        first_msg_id = msg["message_ids"][0] if msg.get("message_ids") else ""
        first_msg_id_str = str(first_msg_id)  # 转成字符串，匹配confirmed的key
        if ocr_texts and first_msg_id_str in confirmed:
            # 已确认：按用户选择的分类
            user_cat = confirmed[first_msg_id_str]
            if user_cat == "invalid":
                msg["category"] = "chat"  # 无效归到闲聊
            elif user_cat in ("sell", "buy", "chat", "notice"):
                msg["category"] = user_cat
            msg["ocr_confirmed"] = True
        elif ocr_texts and msg.get("category") == "pending_ocr":
            # 未确认：用关键词判断
            ocr_text = " ".join(ocr_texts)
            try:
                cat = classify_intent(ocr_text, True)
                if cat == "chat":
                    # 关键词没命中，检查是否有价格关键词
                    has_price = any(kw in ocr_text for kw in PRICE_KEYWORDS)
                    if has_price:
                        cat = "sell"  # 有价格但没关键词，默认出售
                msg["ocr_auto_cat"] = cat
            except:
                msg["ocr_auto_cat"] = "chat"
            msg["ocr_pending"] = True
        
        # 每10张新图片保存一次缓存（断点续传）
        if new_count > 0 and new_count % 10 == 0:
            save_ocr_cache(ocr_cache)
            print(f"  进度: {processed}/{img_count} (新识别{new_count}张, 缓存{cached_count}张)")
    
    # 保存OCR缓存
    save_ocr_cache(ocr_cache)
    pending_count = sum(1 for m in merged_messages if m.get("ocr_pending"))
    confirmed_count = sum(1 for m in merged_messages if m.get("ocr_confirmed"))
    print(f"  OCR完成: {ocr_success}/{img_count} 张识别成功 (新识别{new_count}张, 缓存命中{cached_count}张)")
    print(f"  待确认: {pending_count} 条, 已确认: {confirmed_count} 条")


# ============ 输出 ============

def save_jsonl(messages, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for msg in messages:
            output = {
                "message_ids": msg["message_ids"],
                "first_message_id": msg["message_ids"][0] if msg["message_ids"] else "",
                "time": msg["first_time"],
                "time_str": msg["time_str"],
                "group_id": msg["group_id"],
                "group_name": msg["group_name"],
                "user_id": msg["user_id"],
                "nickname": msg["nickname"],
                "card": msg["card"],
                "text": msg["full_text"],
                "original_text": msg["combined_text"],
                "ocr_text": " ".join(msg.get("ocr_texts", [])),
                "ocr_texts": msg.get("ocr_texts", []),
                "ocr_auto_cat": msg.get("ocr_auto_cat", ""),
                "ocr_pending": msg.get("ocr_pending", False),
                "ocr_confirmed": msg.get("ocr_confirmed", False),
                "category": msg["category"],
                "has_image": msg["has_image"],
                "image_count": msg["image_count"],
                "image_paths": msg.get("image_paths", []),
                "is_image_only": msg["is_image_only"],
                "is_multi_item": msg.get("is_multi_item", False),
                "split_items": msg.get("split_items", []),
                "filtered_stickers": msg.get("filtered_stickers", 0),
                "msg_count": msg["msg_count"],
                "entities": msg["entities"],
                "contact_info": msg.get("contact_info", {"qq": "", "wechat": "", "phone": ""}),
                "correct_category": "",
                "ner_labels": "",
                "note": "",
            }
            f.write(json.dumps(output, ensure_ascii=False) + "\n")
    print(f"  已保存 {len(messages)} 条到: {filepath}")


def generate_review_html(messages, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    cat_colors = {"sell": "#4CAF50", "buy": "#FF9800", "notice": "#2196F3", "chat": "#9E9E9E", "pending_ocr": "#FF5722"}
    cat_labels = {"sell": "出售", "buy": "求购", "notice": "通知", "chat": "闲聊", "pending_ocr": "待OCR"}
    
    # 统计
    stats = defaultdict(int)
    for msg in messages:
        stats[msg["category"]] += 1
    total = len(messages)
    total_stickers = sum(m.get("filtered_stickers", 0) for m in messages)
    multi_count = sum(1 for m in messages if m.get("is_multi_item"))
    contact_count = sum(1 for m in messages if any(m.get("contact_info", {}).values()))
    
    # 读取config.txt中的订阅物品
    initial_want_items = []
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    initial_want_items.append(line)
    
    # 把消息数据序列化为 JSON，交给前端JS渲染
    msg_data = []
    for idx, msg in enumerate(messages):
        contact = msg.get("contact_info", {})
        entities = msg.get("entities", {})
        first_msg_id = msg["message_ids"][0] if msg.get("message_ids") else ""
        
        # 图片相对路径
        img_paths = []
        for img_path in msg.get("image_paths", []):
            full_path = os.path.join("messages", img_path) if not os.path.isabs(img_path) else img_path
            rel_path = os.path.relpath(full_path, os.path.dirname(filepath))
            # Windows反斜杠 → 正斜杠（浏览器需要正斜杠）
            rel_path = rel_path.replace("\\", "/")
            img_paths.append(rel_path)
        
        # 子商品联系方式
        split_items_html = ""
        if msg.get("is_multi_item") and msg.get("split_items"):
            parts = []
            for item in msg["split_items"]:
                sub_contact = item.get("contact_info", {})
                contact_str = ""
                sub_parts = []
                if sub_contact.get("qq"): sub_parts.append(f"QQ:{sub_contact['qq']}")
                if sub_contact.get("wechat"): sub_parts.append(f"微信:{sub_contact['wechat']}")
                if sub_contact.get("phone"): sub_parts.append(f"手机:{sub_contact['phone']}")
                if sub_parts:
                    contact_str = f" <span style='color:#2E7D32'>[联系方式: {' | '.join(sub_parts)}]</span>"
                parts.append(f"<div class='item-split'>商品{item['item_index']+1}: {item.get('text','(无文字)')} ({item['image_count']}张图){contact_str}</div>")
            split_items_html = f"<div class='multi-item'><b>商品拆分:</b>{''.join(parts)}</div>"
        
        # 实体标签
        entity_parts = []
        for it in entities.get("items", []):
            entity_parts.append(f"<span class='entity entity-item'>物品:{it}</span>")
        for pr in entities.get("prices", []):
            entity_parts.append(f"<span class='entity entity-price'>价格:{pr}</span>")
        for co in entities.get("conditions", []):
            entity_parts.append(f"<span class='entity entity-cond'>成色:{co}</span>")
        entity_html = f"<div>{''.join(entity_parts)}</div>" if entity_parts else ""
        
        # 联系方式
        contact_parts = []
        if contact.get("qq"): contact_parts.append(f"QQ: <b>{contact['qq']}</b>")
        if contact.get("wechat"): contact_parts.append(f"微信: <b>{contact['wechat']}</b>")
        if contact.get("phone"): contact_parts.append(f"手机: <b>{contact['phone']}</b>")
        if contact_parts:
            contact_html = f"<div class='contact'>联系方式 → {' | '.join(contact_parts)}</div>"
        elif msg.get("category") in ("sell", "buy"):
            contact_html = f"<div class='contact'>联系方式 → QQ号: <b>{msg.get('user_id','')}</b>（群内用户，可加好友）</div>"
        else:
            contact_html = ""
        
        # OCR - 只在待OCR分类显示，不显示OCR文字，只显示判断结果和确认按钮
        ocr_html = ""
        if msg.get("ocr_texts") and msg.get("category") == "pending_ocr":
            first_msg_id = msg["message_ids"][0] if msg.get("message_ids") else ""
            # 系统自动判断的分类
            auto_cat = msg.get("ocr_auto_cat", "chat")
            cat_label = {"sell": "出售", "buy": "求购", "chat": "闲聊"}.get(auto_cat, "闲聊")
            
            ocr_html = "<div class='ocr-pending'>"
            ocr_html += f"<div class='ocr-auto-cat'>系统判断: <b>{cat_label}</b></div>"
            ocr_html += f"<div class='ocr-confirm-bar'>"
            ocr_html += f"<button class='ocr-btn ocr-btn-correct' onclick='confirmOcr(this,\"{first_msg_id}\",\"{auto_cat}\")'>判断正确</button>"
            ocr_html += f"<button class='ocr-btn' onclick='confirmOcr(this,\"{first_msg_id}\",\"chat\")'>闲聊</button>"
            ocr_html += f"<button class='ocr-btn' onclick='confirmOcr(this,\"{first_msg_id}\",\"buy\")'>求购</button>"
            ocr_html += f"<button class='ocr-btn' onclick='confirmOcr(this,\"{first_msg_id}\",\"sell\")'>出售</button>"
            ocr_html += f"<button class='ocr-btn ocr-btn-skip' onclick='confirmOcr(this,\"{first_msg_id}\",\"invalid\")'>无效</button>"
            ocr_html += f"</div>"
            ocr_html += "</div>"
        
        # 图片
        img_html = ""
        if img_paths:
            img_tags = []
            for p in img_paths:
                clean_path = p.replace("\\", "/").replace("../", "")
                img_tags.append(f"<img src='/messages/{clean_path}' loading='lazy' onerror='this.style.display=\"none\"'>")
            img_html = "<div class='images'>" + "".join(img_tags) + "</div>"
        
        # 合并/表情/多商品标签
        tags_html = ""
        if msg.get("msg_count", 1) > 1:
            tags_html += f"<span class='tag' style='background:#607D8B'>合并{msg['msg_count']}条</span>"
        if msg.get("filtered_stickers", 0) > 0:
            tags_html += f"<span class='tag' style='background:#795548'>过滤表情{msg['filtered_stickers']}</span>"
        if msg.get("is_multi_item"):
            tags_html += f"<span class='tag' style='background:#FF5722'>多商品{len(msg.get('split_items',[]))}件</span>"
        
        full_text = msg.get("full_text", "").replace("<", "&lt;").replace(">", "&gt;")
        
        msg_data.append({
            "_index": idx,
            "cat": msg["category"],
            "color": cat_colors.get(msg["category"], "#9E9E9E"),
            "label": cat_labels.get(msg["category"], msg["category"]),
            "tags": tags_html,
            "time": msg.get("time_str", ""),
            "sender": f"[{msg.get('group_name','')}] {msg.get('card') or msg.get('nickname','')}",
            "text": full_text,
            "ocr": ocr_html,
            "split": split_items_html,
            "entity": entity_html,
            "contact": contact_html,
            "locate": f"群号:{msg.get('group_id','')}",
            "images": img_html,
            "search_text": f"{full_text} {msg.get('group_name','')} {msg.get('card','')} {msg.get('nickname','')}".lower(),
        })
    
    # 统计标签
    stat_tags = ""
    for cat in ["sell", "buy", "notice", "pending_ocr", "chat"]:
        count = stats[cat]
        stat_tags += f"<span class='tag' style='background:{cat_colors[cat]}' data-cat='{cat}'>{cat_labels[cat]} {count}</span>"
    
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
<meta name="theme-color" content="#1565C0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="二手助手">
<meta name="description" content="校园二手群消息聚合搜索">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/messages/labeled/apple-touch-icon.png">
<link rel="icon" type="image/png" href="/messages/labeled/favicon-32.png">
<title>二手交易助手 - {total} 条消息</title>
<style>
:root {{ --primary: #1565C0; --bg: #f5f5f5; --card-bg: #fff; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; margin: 0; background: var(--bg); padding-bottom: env(safe-area-inset-bottom); }}
.toolbar {{ position: sticky; top: 0; z-index: 100; background: #E3F2FD; padding: 10px 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.toolbar h2 {{ margin: 0 0 8px 0; font-size: 18px; }}
.tags-row {{ margin-bottom: 8px; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; color: white; font-size: 12px; margin-right: 5px; cursor: pointer; opacity: 0.6; transition: opacity 0.2s; }}
.tag.active {{ opacity: 1; }}
.tag.no-click {{ cursor: default; opacity: 1; }}
.controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
.controls input {{ padding: 5px 10px; border: 1px solid #90CAF9; border-radius: 4px; font-size: 14px; width: 250px; }}
.controls select {{ padding: 5px; border: 1px solid #90CAF9; border-radius: 4px; font-size: 14px; }}
.controls button {{ padding: 5px 12px; border: none; border-radius: 4px; background: #2196F3; color: white; cursor: pointer; font-size: 14px; }}
.controls button:hover {{ background: #1976D2; }}
.controls button.active {{ background: #1565C0; }}
.page-info {{ font-size: 13px; color: #555; }}
#msgList {{ padding: 10px 20px; }}
.msg {{ background: white; margin: 8px 0; padding: 12px 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.time {{ color: #888; font-size: 12px; }}
.sender {{ color: #333; font-weight: bold; }}
.text {{ margin: 6px 0; line-height: 1.6; }}
.ocr {{ color: #666; font-style: italic; background: #f9f9f9; padding: 5px; border-radius: 4px; margin: 4px 0; }}
.ocr-confirmed {{ color: #2E7D32; background: #E8F5E9; }}
.ocr-pending {{ border: 1px dashed #FF9800; border-radius: 6px; padding: 6px; margin: 4px 0; background: #FFF8E1; }}
.ocr-confirm-bar {{ display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }}
.ocr-btn {{ padding: 4px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; color: #fff; }}
.ocr-btn {{ background: #4CAF50; }}
.ocr-btn:nth-child(2) {{ background: #FF9800; }}
.ocr-btn-skip {{ background: #9E9E9E !important; }}
.ocr-btn:hover {{ opacity: 0.85; }}
.entity {{ display: inline-block; padding: 1px 6px; margin: 2px; border-radius: 3px; font-size: 12px; }}
.entity-item {{ background: #E3F2FD; color: #1565C0; }}
.entity-price {{ background: #FFF3E0; color: #E65100; }}
.entity-cond {{ background: #F3E5F5; color: #6A1B9A; }}
.images {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }}
.images img {{ max-width: 180px; max-height: 180px; border-radius: 4px; cursor: pointer; }}
.stats-line {{ font-size: 13px; color: #555; margin-top: 6px; }}
.multi-item {{ border-left: 3px solid #FF9800; padding-left: 10px; margin: 6px 0; }}
.item-split {{ background: #FFF8E1; padding: 6px 8px; border-radius: 4px; margin: 3px 0; font-size: 13px; }}
.contact {{ background: #E8F5E9; padding: 4px 10px; border-radius: 4px; margin: 4px 0; font-size: 13px; border-left: 3px solid #4CAF50; }}
.contact b {{ color: #2E7D32; }}
.locate {{ background: #FFF3E0; padding: 4px 10px; border-radius: 4px; margin: 4px 0; font-size: 11px; color: #E65100; }}
.loading {{ text-align: center; padding: 30px; color: #888; }}
.pager {{ text-align: center; padding: 15px; }}
.pager button {{ margin: 0 3px; }}
img.modal-img {{ position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); max-width: 90vw; max-height: 90vh; z-index: 200; box-shadow: 0 0 20px rgba(0,0,0,0.5); }}
#overlay {{ position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.7); z-index: 150; display: none; }}
.subscribe-row {{ margin-top: 8px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.subscribe-label {{ font-size: 14px; font-weight: bold; color: #333; }}
.chips-container {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.chip {{ display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #E3F2FD; border: 1px solid #90CAF9; border-radius: 16px; font-size: 13px; color: #1565C0; animation: chipIn 0.2s ease; }}
.chip .remove {{ cursor: pointer; color: #90CAF9; font-weight: bold; margin-left: 4px; font-size: 16px; line-height: 1; }}
.chip .remove:hover {{ color: #C62828; }}
.chip .syn-hint {{ font-size: 10px; color: #888; margin-left: 2px; }}
@keyframes chipIn {{ from {{ opacity: 0; transform: scale(0.8); }} to {{ opacity: 1; transform: scale(1); }} }}
@keyframes msgIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.msg {{ animation: msgIn 0.2s ease; }}

/* ====== 手机端响应式 ====== */
@keyframes msgIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.msg {{ animation: msgIn 0.2s ease; }}

/* 顶部搜索栏 */
.top-bar {{ display: flex; align-items: center; gap: 8px; }}
.search-wrap {{ flex: 1; display: flex; align-items: center; background: #fff; border-radius: 20px; padding: 6px 14px; border: 1px solid #E0E0E0; }}
.search-icon {{ color: #999; flex-shrink: 0; }}
.search-wrap input {{ border: none !important; outline: none; background: transparent; width: 100%; font-size: 16px; padding: 2px 0; }}
.mode-btn {{ background: #4CAF50; color: #fff; border: none; border-radius: 16px; padding: 6px 14px; font-size: 13px; cursor: pointer; flex-shrink: 0; }}
.filter-btn {{ background: #fff; border: 1px solid #E0E0E0; border-radius: 8px; padding: 6px 8px; cursor: pointer; display: flex; align-items: center; color: #666; flex-shrink: 0; }}

/* 分类标签栏 */
.cat-bar {{ display: flex; gap: 8px; margin-top: 8px; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px; }}
.cat-bar .tag {{ flex-shrink: 0; font-size: 13px; padding: 4px 14px; border-radius: 16px; }}

/* 抽屉 */
.drawer {{ background: #fff; margin-top: 8px; border-radius: 12px; padding: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.drawer-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }}
.drawer-item label {{ font-size: 13px; color: #666; white-space: nowrap; }}
.drawer-item select {{ padding: 6px 10px; border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; }}
.drawer-btn {{ background: #E3F2FD; color: #1565C0; border: 1px solid #90CAF9; border-radius: 6px; padding: 5px 14px; font-size: 13px; cursor: pointer; white-space: nowrap; }}
.drawer-btn:hover {{ background: #BBDEFB; }}
.drawer-filters {{ justify-content: flex-start; }}
.filter-group {{ display: flex; align-items: center; gap: 6px; }}
.filter-group label {{ font-size: 13px; color: #888; min-width: 40px; }}
.filter-group select {{ padding: 6px 10px; border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; min-width: 100px; }}

/* 消息卡片 */
.msg {{ background: #fff; border-radius: 12px; padding: 14px; margin: 8px 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-left: none; }}
.msg:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.12); }}
.msg .text {{ font-size: 15px; line-height: 1.5; color: #333; }}
.msg .sender {{ font-size: 12px; color: #999; }}
.msg .time {{ font-size: 11px; color: #bbb; }}
.msg .locate {{ font-size: 10px; color: #ccc; margin-top: 6px; }}
.msg .tag {{ font-size: 11px; padding: 2px 8px; }}
.msg-header {{ display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }}
.msg-footer {{ display: flex; align-items: center; gap: 8px; margin-top: 6px; }}
.images {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
.images img {{ border-radius: 8px; object-fit: cover; }}

/* 价格高亮 */
.price-tag {{ display: inline-block; background: #FFF3E0; color: #FF6F00; font-weight: bold; padding: 2px 8px; border-radius: 6px; font-size: 15px; }}

/* 分页 */
.pager {{ text-align: center; padding: 16px; }}
.pager button {{ background: #fff; border: 1px solid #E0E0E0; border-radius: 8px; padding: 8px 16px; margin: 4px; font-size: 14px; cursor: pointer; }}

/* 模态弹窗 */
.modal-img {{ max-width: 90vw; max-height: 85vh; border-radius: 8px; }}

/* ====== 手机端适配 ====== */
@media (max-width: 768px) {{
  .toolbar {{ padding: 8px 12px; }}
  .search-wrap {{ padding: 8px 12px; }}
  .search-wrap input {{ font-size: 16px; }}
  .cat-bar {{ gap: 6px; }}
  .cat-bar .tag {{ font-size: 12px; padding: 4px 12px; }}
  .msg {{ margin: 6px 10px; padding: 12px; }}
  .msg .text {{ font-size: 15px; }}
  .images img {{ max-width: calc(50vw - 20px); max-height: calc(50vw - 20px); }}
  .drawer {{ padding: 10px; }}
  .drawer-item {{ margin-bottom: 8px; }}
  .drawer-item select {{ font-size: 14px; }}
  .pager button {{ padding: 6px 12px; font-size: 13px; }}
  #jumpPage {{ width: 50px !important; }}
}}

@media (max-width: 380px) {{
  .msg {{ margin: 4px 8px; padding: 10px; }}
  .msg .text {{ font-size: 14px; }}
  .cat-bar .tag {{ font-size: 11px; padding: 3px 10px; }}
}}
</style>
</head>
<body>

<div class="toolbar">
  <div class="top-bar">
    <div class="search-wrap">
      <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
      <input type="text" id="searchBox" placeholder="搜索二手商品..." oninput="onSearch()">
    </div>
    <span id="synonymHint" style="font-size:11px;color:#888;margin-left:4px;"></span>
    <span id="updateTime" style="font-size:11px;color:#999;white-space:nowrap;"></span>
    <button id="refreshBtn" onclick="manualRefresh()" title="手动刷新数据" style="background:none;border:1px solid #ddd;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:12px;color:#666;white-space:nowrap;">↻ 刷新</button>
    <button class="filter-btn" onclick="toggleDrawer()">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="14" y2="12"/><line x1="4" y1="18" x2="18" y2="18"/></svg>
    </button>
  </div>
  
  <div class="cat-bar" id="catBar">
    {stat_tags}
  </div>
  
  <div id="tunnelUrl" class="tunnel-url" style="display:none;margin-top:4px;"></div>
  
  <div class="drawer" id="drawer" style="display:none;">
    <!-- 第1行：我想找 + 添加 -->
    <div class="drawer-item">
      <div class="subscribe-label">我想找:</div>
      <input type="text" id="wantInput" placeholder="输入物品名..." onkeydown="if(event.key==='Enter')addWantItem()" style="padding:5px 10px;border:1px solid #E0E0E0;border-radius:6px;font-size:14px;flex:1;min-width:120px;">
      <button onclick="addWantItem()" class="drawer-btn">添加</button>
      <span id="wantCount" style="font-size:12px;color:#888;"></span>
    </div>
    <div id="wantChips" class="chips-container" style="margin-bottom:10px;"></div>
    <!-- 第2行：分页 -->
    <div class="drawer-item">
      <span class="page-info" id="pageInfo">0 / 0</span>
      <button onclick="prevPage()" class="drawer-btn">上一页</button>
      <button onclick="nextPage()" class="drawer-btn">下一页</button>
      <input type="number" id="jumpPage" placeholder="页码" style="width:50px;padding:5px;border:1px solid #E0E0E0;border-radius:6px;font-size:14px;">
      <button onclick="jumpToPage()" class="drawer-btn">跳转</button>
    </div>
    <!-- 第3行：群筛选 / 排序 / 每页，整齐排列 -->
    <div class="drawer-item drawer-filters">
      <div class="filter-group">
        <label>群筛选</label>
        <select id="groupFilter" onchange="onFilter()">
          <option value="">全部群</option>
        </select>
      </div>
      <div class="filter-group">
        <label>排序</label>
        <select id="sortBy" onchange="onFilter()">
          <option value="time_desc">最新优先</option>
          <option value="time_asc">最早优先</option>
        </select>
      </div>
      <div class="filter-group">
        <label>每页</label>
        <select id="pageSize" onchange="onFilter()">
          <option value="50">50条</option>
          <option value="100">100条</option>
          <option value="200">200条</option>
        </select>
      </div>
    </div>
  </div>
</div>

<div id="msgList"></div>
<div id="overlay" onclick="closeModal()"></div>

<div class="pager" id="pager"></div>

<script>
const ALL_DATA = {json.dumps(msg_data, ensure_ascii=False)};
const CAT_COLORS = {json.dumps(cat_colors)};
const CAT_LABELS = {json.dumps(cat_labels)};
const SYNONYM_MAP = {json.dumps(SYNONYM_MAP, ensure_ascii=False)};

let filtered = ALL_DATA.slice();
let currentPage = 0;
let pageSize = 50;
let activeCat = null;
let searchMode = 'fuzzy';  // 'strict' 或 'fuzzy'

function expandQuery(q) {{
  // 第1层：同义词扩展（精确映射表）
  let terms = [q];
  for (const [key, synonyms] of Object.entries(SYNONYM_MAP)) {{
    if (q.includes(key.toLowerCase())) {{
      terms = terms.concat(synonyms.map(s => s.toLowerCase()));
    }}
    for (const syn of synonyms) {{
      if (q.includes(syn.toLowerCase())) {{
        terms.push(key.toLowerCase());
        break;
      }}
    }}
  }}
  return [...new Set(terms)];
}}

function extractCoreChars(q) {{
  // 第2层：字词拆分模糊匹配
  // 去掉常见无意义后缀字，提取核心字
  const fillerChars = new Set(['子', '的', '了', '是', '在', '有', '和', '与', '或', '个', '些', '这', '那']);
  let chars = [];
  for (const ch of q) {{
    if (!fillerChars.has(ch) && ch.trim()) {{
      chars.push(ch);
    }}
  }}
  return chars;
}}

function matchMessage(searchText, rawQ, terms, coreChars) {{
  if (searchMode === 'strict') {{
    // 严格模式：只匹配同义词表 + 精确包含
    for (const term of terms) {{
      if (searchText.includes(term)) return true;
    }}
    return false;
  }} else {{
    // 宽松模式：同义词匹配 + 核心字模糊匹配
    // 先试同义词
    for (const term of terms) {{
      if (searchText.includes(term)) return true;
    }}
    // 再试核心字（任一核心字命中即匹配）
    if (coreChars.length >= 2) {{
      for (const ch of coreChars) {{
        if (searchText.includes(ch)) return true;
      }}
    }} else if (coreChars.length === 1) {{
      // 单字搜索时要求精确匹配该字
      if (searchText.includes(coreChars[0])) return true;
    }}
    return false;
  }}
}}

function applyFilters() {{
  const rawQ = document.getElementById('searchBox').value.trim().toLowerCase();
  const groupVal = document.getElementById('groupFilter').value;
  const sortVal = document.getElementById('sortBy').value;
  pageSize = parseInt(document.getElementById('pageSize').value);
  
  if (semanticResults && rawQ) {{
    // 语义搜索模式：用API返回的结果排序
    // 建立index→score的映射
    const scoreMap = {{}};
    for (const r of semanticResults) {{
      scoreMap[r.index] = r.score;
    }}
    // 按相似度排序，只显示API返回的消息
    filtered = ALL_DATA.filter(m => {{
      if (scoreMap[m._index] === undefined) return false;
      if (groupVal && !m.sender.includes(groupVal)) return false;
      return true;
    }});
    // 按相似度排序
    filtered.sort((a, b) => (scoreMap[b._index] || 0) - (scoreMap[a._index] || 0));
  }} else {{
    // 关键词搜索模式（原有逻辑）
    let terms = [];
    let coreChars = [];
    if (rawQ) {{
      terms = expandQuery(rawQ);
      coreChars = extractCoreChars(rawQ);
    }}
    filtered = ALL_DATA.filter(m => {{
      if (!activeCat && m.cat === 'chat') return false;
      if (activeCat && m.cat !== activeCat) return false;
      if (rawQ) {{
        if (!matchMessage(m.search_text, rawQ, terms, coreChars)) return false;
      }}
      if (groupVal && !m.sender.includes(groupVal)) return false;
      return true;
    }});
    if (sortVal === 'time_asc') {{
      filtered.sort((a,b) => (a.time || '').localeCompare(b.time || ''));
    }} else {{
      filtered.sort((a,b) => (b.time || '').localeCompare(a.time || ''));
    }}
  }}
  
  currentPage = 0;
  render();
}}

function onSearch() {{
  // 显示同义词扩展提示
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  const hint = document.getElementById('synonymHint');
  if (q) {{
    const terms = expandQuery(q);
    const extra = terms.filter(t => t !== q);
    if (extra.length > 0) {{
      hint.textContent = '+ ' + extra.join(', ');
      hint.style.color = '#4CAF50';
    }} else {{
      hint.textContent = '';
    }}
  }} else {{
    hint.textContent = '';
  }}
  applyFilters();
}}

function onFilter() {{ applyFilters(); }}

function toggleDrawer() {{
  const d = document.getElementById('drawer');
  d.style.display = d.style.display === 'none' ? 'block' : 'none';
}}

// ====== 语义搜索（始终开启）======
let semanticResults = null;
let semanticTimer = null;

function onSearch() {{
  // 语义搜索：延迟300ms调API
  clearTimeout(semanticTimer);
  semanticTimer = setTimeout(() => {{
    const q = document.getElementById('searchBox').value.trim();
    if (!q) {{
      semanticResults = null;
      applyFilters();
      return;
    }}
    // 调用语义搜索API
    fetch('/api/search?q=' + encodeURIComponent(q) + (activeCat ? '&cat=' + activeCat : ''))
      .then(r => r.json())
      .then(data => {{
        if (Array.isArray(data)) {{
          semanticResults = data;
          applyFilters();
        }}
      }})
      .catch(() => {{
        // API失败时回退到关键词模式
        semanticResults = null;
        applyFilters();
      }});
  }}, 300);
}}

// ====== 订阅物品 Tag Input ======
const MAX_WANT_ITEMS = 10;
let wantItems = [];

// 确认OCR结果
function confirmOcr(btn, msgId, cat) {{
  // 禁用按钮防止重复点击
  btn.disabled = true;
  fetch('/api/confirm_ocr', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: 'msg_id=' + encodeURIComponent(msgId) + '&cat=' + cat
  }}).then(r => r.json()).then(data => {{
    if (data.ok) {{
      // 找到卡片，变灰
      const card = btn.closest('.msg-card') || btn.closest('.card') || btn.parentElement.parentElement;
      if (card) {{
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
      }}
      // 替换按钮区域
      const bar = btn.parentElement;
      const labels = {{sell:'出售', buy:'求购', chat:'闲聊', invalid:'无效'}};
      const colors = {{sell:'#2E7D32', buy:'#E65100', chat:'#757575', invalid:'#D32F2F'}};
      bar.innerHTML = '<span style="color:' + (colors[cat]||'#757575') + ';font-weight:bold;font-size:14px;">&#10003; 已确认: ' + (labels[cat]||cat) + '</span>';
    }} else {{
      btn.disabled = false;
      alert('确认失败: ' + (data.error || '未知错误'));
    }}
  }}).catch((e) => {{
    btn.disabled = false;
    alert('网络错误: ' + e);
  }});
}}

function loadWantItems() {{
  try {{
    const saved = localStorage.getItem('wantItems');
    if (saved) wantItems = JSON.parse(saved);
  }} catch(e) {{ wantItems = []; }}
  // 如果localStorage为空，尝试从内嵌数据读取
  if (wantItems.length === 0 && typeof INITIAL_WANT_ITEMS !== 'undefined') {{
    wantItems = INITIAL_WANT_ITEMS.slice();
  }}
  renderChips();
}}

function saveWantItems() {{
  localStorage.setItem('wantItems', JSON.stringify(wantItems));
  // 自动保存到服务器config.txt
  fetch('/api/save_config', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: 'items=' + encodeURIComponent(JSON.stringify(wantItems))
  }}).catch(() => {{}});
}}

function addWantItem() {{
  const input = document.getElementById('wantInput');
  const val = input.value.trim();
  if (!val) return;
  if (wantItems.length >= MAX_WANT_ITEMS) {{
    alert('最多只能订阅 ' + MAX_WANT_ITEMS + ' 个物品');
    return;
  }}
  if (wantItems.includes(val)) {{
    alert('已经订阅过"' + val + '"了');
    input.value = '';
    return;
  }}
  wantItems.push(val);
  input.value = '';
  saveWantItems();
  renderChips();
  applyFilters();
}}

function removeWantItem(idx) {{
  wantItems.splice(idx, 1);
  saveWantItems();
  renderChips();
  applyFilters();
}}

function renderChips() {{
  const container = document.getElementById('wantChips');
  const countEl = document.getElementById('wantCount');
  countEl.textContent = wantItems.length + '/' + MAX_WANT_ITEMS;
  
  let html = '';
  for (let i = 0; i < wantItems.length; i++) {{
    const item = wantItems[i];
    // 查找同义词提示
    let synHint = '';
    if (SYNONYM_MAP[item]) {{
      synHint = `<span class="syn-hint">+${{SYNONYM_MAP[item].length}}同义词</span>`;
    }}
    html += `<span class="chip">${{item}}${{synHint}}<span class="remove" onclick="removeWantItem(${{i}})">×</span></span>`;
  }}
  container.innerHTML = html;
}}

function getWantSearchTerms() {{
  // 获取所有订阅物品的搜索词（含同义词扩展+核心字）
  let terms = [];
  for (const item of wantItems) {{
    terms = terms.concat(expandQuery(item.toLowerCase()));
    terms = terms.concat(extractCoreChars(item.toLowerCase()));
  }}
  return [...new Set(terms)];
}}

function toggleCat(cat) {{
  if (activeCat === cat) {{
    activeCat = null;
  }} else {{
    activeCat = cat;
  }}
  document.querySelectorAll('.tag[data-cat]').forEach(t => {{
    t.classList.toggle('active', t.dataset.cat === activeCat);
  }});
  applyFilters();
}}

function render() {{
  const list = document.getElementById('msgList');
  const start = currentPage * pageSize;
  const end = Math.min(start + pageSize, filtered.length);
  const pageData = filtered.slice(start, end);
  
  if (pageData.length === 0) {{
    list.innerHTML = '<div class="loading">没有匹配的消息</div>';
  }} else {{
    // 计算订阅物品搜索词
    const wantTerms = wantItems.length > 0 ? getWantSearchTerms() : [];
    let html = '';
    for (const m of pageData) {{
      // 检查是否命中订阅物品
      let wantHit = false;
      if (wantTerms.length > 0) {{
        for (const term of wantTerms) {{
          if (m.search_text.includes(term)) {{ wantHit = true; break; }}
        }}
      }}
      const wantTag = wantHit ? `<span class="tag" style="background:#8E24AA;animation:chipIn 0.3s ease;">★命中订阅</span>` : '';
      const msgStyle = wantHit ? 'border-left:4px solid #8E24AA;background:#FAF5FC;' : '';
      // 价格高亮
      let displayText = m.text || '';
      if (m.price) {{
        const priceStr = String(m.price);
        displayText = displayText.replace(priceStr, `<span class="price-tag">${{priceStr}}</span>`);
      }}
      html += `<div class="msg" style="${{msgStyle}}">
        <div class="msg-header">
          <span class="tag" style="background:${{m.color}}">${{m.label}}</span>${{m.tags}}${{wantTag}}
          <span class="time">${{m.time}}</span>
        </div>
        ${{displayText ? `<div class="text">${{displayText}}</div>` : ''}}
        <div class="msg-footer">
          <span class="sender">${{m.sender}}</span>
          ${{m.contact}}
        </div>
        ${{m.ocr}}
        ${{m.split}}
        ${{m.entity}}
        <div class="locate">${{m.locate}}</div>
        ${{m.images}}
      </div>`;
    }}
    list.innerHTML = html;
    
    // 点击图片放大
    list.querySelectorAll('img').forEach(img => {{
      img.onclick = function() {{ openModal(this.src); }};
    }});
  }}
  
  // 更新分页信息
  const totalPages = Math.ceil(filtered.length / pageSize);
  document.getElementById('pageInfo').innerHTML = 
    (filtered.length > 0 ? (currentPage+1) + '/' + totalPages + '页 (' + (start+1) + '-' + end + '条)' : '0 结果');
  
  // 分页按钮
  const pager = document.getElementById('pager');
  let pHtml = '';
  if (currentPage > 0) pHtml += `<button onclick="goPage(${{currentPage-1}})">上一页</button> `;
  // 页码按钮
  const maxBtns = 10;
  let s = Math.max(0, currentPage - Math.floor(maxBtns/2));
  let e = Math.min(totalPages, s + maxBtns);
  s = Math.max(0, e - maxBtns);
  for (let i = s; i < e; i++) {{
    pHtml += `<button onclick="goPage(${{i}})" style="${{i===currentPage?'background:#1565C0':'background:#2196F3'}}">${{i+1}}</button> `;
  }}
  if (currentPage < totalPages - 1) pHtml += `<button onclick="goPage(${{currentPage+1}})">下一页</button>`;
  pager.innerHTML = pHtml;
}}

function goPage(p) {{ currentPage = p; render(); window.scrollTo(0,0); }}
function prevPage() {{ if(currentPage>0){{currentPage--;render();window.scrollTo(0,0);}} }}
function nextPage() {{ const tp=Math.ceil(filtered.length/pageSize); if(currentPage<tp-1){{currentPage++;render();window.scrollTo(0,0);}} }}
function jumpToPage() {{
  const val = parseInt(document.getElementById('jumpPage').value);
  const tp = Math.ceil(filtered.length / pageSize);
  if (val >= 1 && val <= tp) {{ goPage(val - 1); }}
}}

function openModal(src) {{
  const overlay = document.getElementById('overlay');
  overlay.innerHTML = `<img class="modal-img" src="${{src}}">`;
  overlay.style.display = 'block';
}}
function closeModal() {{
  document.getElementById('overlay').style.display = 'none';
  document.getElementById('overlay').innerHTML = '';
}}

// 填充群列表
const groups = [...new Set(ALL_DATA.map(m => {{
  const match = m.sender.match(/\\[(.+?)\\]/);
  return match ? match[1] : '';
}}))].filter(Boolean);
const groupSelect = document.getElementById('groupFilter');
groups.forEach(g => {{
  const opt = document.createElement('option');
  opt.value = g;
  opt.textContent = g;
  groupSelect.appendChild(opt);
}});

// 点击统计标签筛选
document.querySelectorAll('.tag[data-cat]').forEach(t => {{
  t.onclick = function() {{ toggleCat(this.dataset.cat); }};
}});

// 读取已存在的config.txt作为初始订阅数据
const INITIAL_WANT_ITEMS = {json.dumps(initial_want_items, ensure_ascii=False)};

// 加载订阅物品 → 初始渲染
loadWantItems();
render();

// ====== 更新时间显示 + 静默刷新 ======
let lastUpdateTime = new Date();  // 数据最后更新时间（初始为页面加载时间）
let lastDataCount = ALL_DATA.length;
let lastMsgId = ALL_DATA.length > 0 ? (ALL_DATA[ALL_DATA.length-1].message_ids || [''])[0] : '';

function showUpdateTime() {{
  const now = new Date();
  const diff = Math.floor((now - lastUpdateTime) / 1000);
  let text;
  if (diff < 5) text = '刚刚更新';
  else if (diff < 60) text = diff + '秒前更新';
  else if (diff < 3600) text = Math.floor(diff/60) + '分钟前更新';
  else text = Math.floor(diff/3600) + '小时前更新';
  const el = document.getElementById('updateTime');
  if (el) el.textContent = text;
}}
showUpdateTime();

// 每30秒静默刷新：重新获取HTML，提取最新的ALL_DATA替换
setInterval(() => {{
  fetch('/messages/labeled/review.html?t=' + Date.now())
    .then(r => r.text())
    .then(html => {{
      // 提取最新的 ALL_DATA JSON
      const match = html.match(/const ALL_DATA = (\[[\s\S]*?\]);/);
      if (match) {{
        try {{
          const newData = JSON.parse(match[1]);
          // 检查是否有变化：数量变了 或 最后一条消息id变了
          const newLastId = newData.length > 0 ? (newData[newData.length-1].message_ids || [''])[0] : '';
          if (newData.length !== lastDataCount || newLastId !== lastMsgId) {{
            ALL_DATA.length = 0;
            ALL_DATA.push(...newData);
            lastDataCount = newData.length;
            lastMsgId = newLastId;
            lastUpdateTime = new Date();  // 更新"最后更新时间"
            applyFilters();  // 重新过滤+渲染，保留当前搜索状态和分类
          }}
        }} catch(e) {{}}
      }}
    }})
    .catch(() => {{}});
}}, 30000);

// 每5秒更新"X秒前更新"显示（不需要每秒）
setInterval(showUpdateTime, 5000);

// ====== 手动刷新按钮 ======
function manualRefresh() {{
  const btn = document.getElementById('refreshBtn');
  if (!btn) return;
  btn.textContent = '⏳ 刷新中...';
  btn.disabled = true;
  fetch('/api/refresh')
    .then(r => r.json())
    .then(data => {{
      if (data.status === 'started') {{
        // 等待3秒后重新加载页面数据
        setTimeout(() => {{
          fetch('/messages/labeled/review.html?t=' + Date.now())
            .then(r => r.text())
            .then(html => {{
              const match = html.match(/const ALL_DATA = (\[[\s\S]*?\]);/);
              if (match) {{
                const newData = JSON.parse(match[1]);
                ALL_DATA.length = 0;
                ALL_DATA.push(...newData);
                lastDataCount = newData.length;
                lastUpdateTime = new Date();
                applyFilters();
                btn.textContent = '✓ 已刷新';
                btn.disabled = false;
                setTimeout(() => {{ btn.textContent = '↻ 刷新'; }}, 2000);
              }}
            }});
        }}, 3000);
      }}
    }})
    .catch(() => {{
      btn.textContent = '✗ 刷新失败';
      btn.disabled = false;
      setTimeout(() => {{ btn.textContent = '↻ 刷新'; }}, 2000);
    }});
}}

// ====== 读取公网地址并显示 ======
fetch('/messages/labeled/tunnel_url.txt?t=' + Date.now())
  .then(r => r.text())
  .then(url => {{
    url = url.trim();
    if (url) {{
      const el = document.getElementById('tunnelUrl');
      if (el) {{
        el.innerHTML = '📱 <a href="' + url + '" target="_blank" style="color:#07c;font-size:11px;text-decoration:none;">' + url + '</a>';
        el.style.display = 'block';
      }}
    }}
  }})
  .catch(() => {{}});

// ====== PWA Service Worker 注册 ======
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => {{
    navigator.serviceWorker.register('/sw.js').then(() => {{
      console.log('PWA已注册，可添加到桌面');
    }}).catch((err) => {{
      console.log('PWA注册失败:', err);
    }});
  }});
}}

// ====== PWA 安装提示 ======
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {{
  e.preventDefault();
  deferredPrompt = e;
  // 显示安装提示
  const installBar = document.createElement('div');
  installBar.id = 'installBar';
  installBar.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#1565C0;color:white;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;z-index:200;box-shadow:0 -2px 8px rgba(0,0,0,0.2);';
  installBar.innerHTML = `
    <span style="font-size:14px;">📱 添加到桌面，像App一样使用</span>
    <div>
      <button id="installBtn" style="background:white;color:#1565C0;border:none;padding:6px 16px;border-radius:4px;font-weight:bold;margin-right:8px;cursor:pointer;">安装</button>
      <button id="closeInstallBtn" style="background:transparent;color:white;border:1px solid white;padding:6px 10px;border-radius:4px;cursor:pointer;">×</button>
    </div>
  `;
  document.body.appendChild(installBar);
  
  document.getElementById('installBtn').onclick = () => {{
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(() => {{
      deferredPrompt = null;
      document.getElementById('installBar').remove();
    }});
  }};
  document.getElementById('closeInstallBtn').onclick = () => {{
    document.getElementById('installBar').remove();
  }};
}});
</script>
</body>
</html>"""
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML预览: {filepath}")


def find_latest_file(directory):
    if not os.path.exists(directory):
        return None
    files = [f for f in os.listdir(directory) if f.endswith(".jsonl")]
    if not files:
        return None
    files.sort(reverse=True)
    return os.path.join(directory, files[0])


def main():
    print("="*60)
    print("  数据预处理工具 v2")
    print("="*60)
    
    input_file = INPUT_FILE or find_latest_file(INPUT_DIR)
    if not input_file:
        print(f"\n[错误] 在 {INPUT_DIR} 中没有找到JSONL文件")
        return
    
    print(f"\n输入文件: {input_file}")
    
    messages = load_messages(input_file)
    print(f"加载 {len(messages)} 条原始消息")
    
    if not messages:
        return
    
    # 第1步：合并消息（含表情包过滤）
    print(f"\n--- 第1步：合并消息 + 过滤表情包（窗口={MERGE_TIME_WINDOW}秒）---")
    merged = merge_messages(messages, MERGE_TIME_WINDOW)
    total_stickers = sum(m.get("filtered_stickers", 0) for m in merged)
    multi_items = 0
    for m in merged:
        finalize_merged(m)
        if m.get("is_multi_item"):
            multi_items += 1
    
    # 过滤空消息（表情包全被过滤掉、又没文字的）
    empty_count = sum(1 for m in merged if m.get("is_empty"))
    merged = [m for m in merged if not m.get("is_empty")]
    
    print(f"  合并后: {len(merged)} 条（原{len(messages)}条）")
    print(f"  过滤表情包: {total_stickers} 张 | 丢弃空消息: {empty_count} 条")
    print(f"  多商品消息: {multi_items} 条（已拆分标注）")
    
    # 第2步：OCR
    print(f"\n--- 第2步：图片OCR ---")
    run_ocr(merged)
    
    # 第3步：补充联系方式提取（分类和实体在OCR时已处理，无OCR的消息补充联系方式）
    print(f"\n--- 第3步：补充联系方式提取 ---")
    for msg in merged:
        if not msg.get("contact_info"):
            all_text = msg.get("full_text", "") or msg["combined_text"]
            msg["contact_info"] = extract_contact_info(all_text)
    
    # 统计
    print(f"\n--- 统计 ---")
    stats = defaultdict(int)
    for msg in merged:
        stats[msg["category"]] += 1
    total = len(merged)
    labels = {"sell": "出售", "buy": "求购", "notice": "通知", "pending_ocr": "待OCR", "chat": "闲聊"}
    for cat in ["sell", "buy", "notice", "pending_ocr", "chat"]:
        count = stats[cat]
        pct = f"{count/total*100:.1f}%" if total > 0 else "0%"
        print(f"  {labels[cat]:4s}: {count:5d} ({pct})")
    
    img_msgs = sum(1 for m in merged if m["has_image"])
    ocr_msgs = sum(1 for m in merged if m.get("ocr_texts"))
    contact_msgs = sum(1 for m in merged if any(m.get("contact_info", {}).values()))
    print(f"  含图片: {img_msgs} 条 | OCR有文字: {ocr_msgs} 条")
    print(f"  过滤表情包: {total_stickers} 张 | 多商品: {multi_items} 条 | 含联系方式: {contact_msgs} 条")
    
    # 保存
    print(f"\n--- 保存 ---")
    save_jsonl(merged, OUTPUT_FILE)
    generate_review_html(merged, REVIEW_HTML)
    
    print(f"\n{'='*60}")
    print(f"  完成！")
    print(f"  标注数据: {OUTPUT_FILE}")
    print(f"  HTML预览: {REVIEW_HTML}")
    print(f"\n  下一步:")
    print(f"  1. 浏览器打开HTML检查效果")
    print(f"  2. 在JSONL中修正 correct_category 和 ner_labels")
    print(f"  3. 用标注数据训练BERT模型")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()


def process_all(verbose=True):
    """
    供外部调用的预处理接口。
    读取 raw/ 目录所有JSONL，合并处理，输出 ready_to_label.jsonl 和 review.html
    返回处理后的消息列表
    """
    if verbose:
        print("[预处理] 开始...")
    
    # 读取所有raw文件并合并
    all_messages = []
    raw_files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith(".jsonl")])
    for rf in raw_files:
        filepath = os.path.join(INPUT_DIR, rf)
        msgs = load_messages(filepath)
        all_messages.extend(msgs)
    
    if not all_messages:
        if verbose:
            print("[预处理] 没有找到消息数据")
        return []
    
    if verbose:
        print(f"[预处理] 加载 {len(all_messages)} 条消息（来自{len(raw_files)}个文件）")
    
    # 合并
    merged = merge_messages(all_messages, MERGE_TIME_WINDOW)
    total_stickers = sum(m.get("filtered_stickers", 0) for m in merged)
    for m in merged:
        finalize_merged(m)
    merged = [m for m in merged if not m.get("is_empty")]
    
    # OCR（如果可用）
    run_ocr(merged)
    
    # 补充联系方式
    for msg in merged:
        if not msg.get("contact_info"):
            all_text = msg.get("full_text", "") or msg["combined_text"]
            msg["contact_info"] = extract_contact_info(all_text)
    
    # 批量kNN分类（对所有关键词分类为chat的消息一次性做kNN）
    try:
        from knn_classifier import batch_knn_classify, NEW_SELL_KEYWORDS, NEW_BUY_KEYWORDS
        
        # 收集需要kNN分类的消息（关键词分类为chat的）
        knn_indices = []
        knn_texts = []
        for i, msg in enumerate(merged):
            if msg.get("category") == "chat":
                text = msg.get("full_text", "") or msg["combined_text"]
                # 先检查新关键词
                hit_new = False
                for kw in NEW_SELL_KEYWORDS:
                    if kw in text:
                        msg["category"] = "sell"
                        msg["_knn_classified"] = True
                        hit_new = True
                        break
                if not hit_new:
                    for kw in NEW_BUY_KEYWORDS:
                        if kw in text:
                            msg["category"] = "buy"
                            msg["_knn_classified"] = True
                            hit_new = True
                            break
                # 没命中新关键词，加入kNN待分类列表
                if not hit_new and len(text.strip()) >= 4:
                    knn_indices.append(i)
                    knn_texts.append(text)
        
        if knn_texts:
            if verbose:
                print(f"[预处理] 批量kNN分类 {len(knn_texts)} 条chat消息...")
            knn_cats = batch_knn_classify(knn_texts)
            changed = 0
            for idx, cat in zip(knn_indices, knn_cats):
                if cat != "chat":
                    merged[idx]["category"] = cat
                    merged[idx]["_knn_classified"] = True
                    changed += 1
            if verbose:
                print(f"[预处理] kNN修正了 {changed} 条（共{len(knn_texts)}条）")
    except ImportError:
        if verbose:
            print("[预处理] kNN模块未安装，跳过语义分类")
    except Exception as e:
        if verbose:
            print(f"[预处理] kNN分类失败: {e}，跳过")
    
    # 保存
    save_jsonl(merged, OUTPUT_FILE)
    generate_review_html(merged, REVIEW_HTML)
    
    if verbose:
        sell_count = sum(1 for m in merged if m["category"] == "sell")
        buy_count = sum(1 for m in merged if m["category"] == "buy")
        print(f"[预处理] 完成: {len(merged)}条, 出售{sell_count}条, 求购{buy_count}条")
    
    return merged
