# -*- coding: utf-8 -*-
"""数据真实性：重复检测、广告/虚假识别、可信度评分"""
import re
from difflib import SequenceMatcher

from config import AD_KEYWORDS, URL_PATTERN, PRICE_SANE_MAX, DUP_SIM_THRESHOLD

_url_re = re.compile(URL_PATTERN, re.I)
_ws_re = re.compile(r"\s+")


def normalize(text):
    return _ws_re.sub("", (text or "").lower())


def text_sim(a, b):
    """短文本相似度：SequenceMatcher（对 1k 量级数据足够快）"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def detect_duplicates(items):
    """检测重复消息。
    - 同一用户发布的高相似消息 → 合并为一条（保留最新，记录 repost_count）
    - 不同用户发布的完全相同长文本 → 标记 cross_dup（疑似转发/中介）
    返回处理后的列表（已去重）。
    """
    # 按用户分组
    by_user = {}
    for it in items:
        by_user.setdefault(it["user_id"], []).append(it)

    keep = []
    for uid, msgs in by_user.items():
        msgs.sort(key=lambda m: m["time"])  # 旧→新
        merged = []  # [(norm_text, item)]
        for m in msgs:
            nt = normalize(m["text"] + (m.get("ocr_text") or ""))
            dup_of = None
            for i, (pnt, prev) in enumerate(merged):
                if len(nt) >= 6 and len(pnt) >= 6 and text_sim(nt, pnt) >= DUP_SIM_THRESHOLD:
                    dup_of = i
                    break
            if dup_of is not None:
                # 保留最新的一条，累计重发次数
                _, prev = merged[dup_of]
                m["repost_count"] = prev.get("repost_count", 0) + 1
                m["first_post_time"] = prev.get("first_post_time", prev["time"])
                merged[dup_of] = (nt, m)
            else:
                m["repost_count"] = 0
                merged.append((nt, m))
        keep.extend(it for _, it in merged)

    # 跨用户完全重复（长文本）
    seen = {}
    for it in keep:
        nt = normalize(it["text"])
        if len(nt) >= 30:
            if nt in seen:
                it["cross_dup"] = True
                seen[nt]["cross_dup"] = True
            else:
                seen[nt] = it

    return keep


def assess_authenticity(item):
    """给单条消息打真实性标记与可信度分（0-100）"""
    text = (item.get("text") or "") + " " + (item.get("ocr_text") or "")
    flags = []
    score = 100

    for kw in AD_KEYWORDS:
        if kw in text:
            flags.append("ad")
            score -= 45
            break

    if _url_re.search(text):
        flags.append("link")
        score -= 15

    prices = item.get("prices") or []
    if prices and max(prices) > PRICE_SANE_MAX:
        flags.append("price_weird")
        score -= 20

    if item.get("cross_dup"):
        flags.append("cross_dup")
        score -= 30

    if item.get("repost_count", 0) >= 3:
        flags.append("frequent_repost")
        score -= 10

    # 无任何联系方式且无 user_id 兜底（几乎不会发生）
    c = item.get("contact") or {}
    if not any([c.get("qq"), c.get("wechat"), c.get("phone"), item.get("user_id")]):
        flags.append("no_contact")
        score -= 20

    score = max(0, min(100, score))
    if "ad" in flags:
        level = "ad"          # 广告/虚假
    elif score >= 80:
        level = "trusted"     # 可信
    else:
        level = "doubtful"    # 存疑
    return flags, score, level
