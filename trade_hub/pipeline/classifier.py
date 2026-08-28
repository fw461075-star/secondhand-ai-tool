# -*- coding: utf-8 -*-
"""意图分类（规则 + 可选向量 kNN 兜底）与商品类别分类"""
import os
import re
import json

from config import (
    SELL_KEYWORDS, SELL_WEAK, BUY_KEYWORDS, BUY_WEAK, NOTICE_KEYWORDS,
    PRICE_KEYWORDS, CHAT_SIGNALS, CATEGORY_RULES, OTHER_CATEGORY,
    MANUAL_LABELS_FILE, DATA_FILE, MODELS_DIR,
)

ALL_ITEM_WORDS = [w for _, _, kws in CATEGORY_RULES for w in kws]

PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:块|元|r|R|￥|¥|米)|[¥￥]\s*(\d+(?:\.\d+)?)")


def extract_prices(text):
    """提取消息中的价格数字列表"""
    prices = []
    for m in PRICE_RE.finditer(text or ""):
        v = m.group(1) or m.group(2)
        try:
            f = float(v)
            if 0 < f < 1000000:
                prices.append(f)
        except ValueError:
            pass
    return prices


def has_price(text):
    return bool(PRICE_RE.search(text or "")) or any(k in (text or "") for k in PRICE_KEYWORDS)


def has_item(text):
    t = (text or "").lower()
    return any(w.lower() in t for w in ALL_ITEM_WORDS)


def classify_intent_rule(text, has_image=False):
    """规则意图分类。返回 (category, confidence)
    category: sell / buy / notice / chat
    confidence: high / low（low 表示建议用向量模型复核）
    """
    t = (text or "").strip()
    if not t:
        return ("chat", "high")
    tl = t.lower()

    # 通知类
    for kw in NOTICE_KEYWORDS:
        if kw.lower() in tl:
            return ("notice", "high")

    strong_sell = any(kw in t for kw in SELL_KEYWORDS)
    strong_buy = any(kw in t for kw in BUY_KEYWORDS)
    price = has_price(t)
    item = has_item(t)

    if strong_sell and not strong_buy:
        return ("sell", "high")
    if strong_buy and not strong_sell:
        return ("buy", "high")
    if strong_sell and strong_buy:
        # 同时出现，看谁在前
        si = min((t.find(k) for k in SELL_KEYWORDS if k in t), default=999)
        bi = min((t.find(k) for k in BUY_KEYWORDS if k in t), default=999)
        return ("sell" if si <= bi else "buy", "low")

    weak_sell = any(kw in t for kw in SELL_WEAK)
    weak_buy = any(kw in t for kw in BUY_WEAK)

    # 弱信号需要配合物品词或价格
    if weak_sell and (price or item):
        return ("sell", "low" if not (price and item) else "high")
    if weak_buy and (price or item):
        return ("buy", "low" if not (price and item) else "high")

    # 明显闲聊信号
    if any(s in t for s in CHAT_SIGNALS):
        return ("chat", "high")

    # 有物品+价格但没有买卖词 → 大概率出售
    if price and item:
        return ("sell", "low")

    return ("chat", "low" if (item or price or has_image) else "high")


def classify_category(text, ocr_text=""):
    """商品类别分类：按关键词计分，命中多者胜；靠前类别优先"""
    t = ((text or "") + " " + (ocr_text or "")).lower()
    best = None
    best_score = 0
    for cid, name, kws in CATEGORY_RULES:
        score = 0
        for kw in kws:
            if kw.lower() in t:
                score += max(len(kw), 2)  # 长词权重更高
        if score > best_score:
            best_score = score
            best = cid
    return best if best else OTHER_CATEGORY[0]


# ============ 可选：向量 kNN 复核 ============
_model = None
_ref_vecs = None
_ref_cats = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5", cache_folder=MODELS_DIR)
    return _model


def build_knn_reference(messages):
    """用高置信度规则分类结果 + 人工标注构建参考库"""
    global _ref_vecs, _ref_cats
    import numpy as np

    ref_texts, ref_cats = [], []
    # 人工标注（历史遗留的 suspicious 复核数据）
    if os.path.exists(MANUAL_LABELS_FILE):
        with open(MANUAL_LABELS_FILE, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                label = d.get("label")
                if label in ("sell", "buy", "chat"):
                    ref_texts.append(d["text"])
                    ref_cats.append(label)
                elif label == "correct" and d.get("original_cat") in ("sell", "buy", "chat"):
                    ref_texts.append(d["text"])
                    ref_cats.append(d["original_cat"])

    # 高置信度样本（每类最多 150 条）
    counts = {"sell": 0, "buy": 0, "chat": 0, "notice": 0}
    for m in messages:
        text = m.get("text", "")
        if not text or len(text) < 4:
            continue
        cat, conf = classify_intent_rule(text, m.get("has_image"))
        if conf == "high" and cat in counts and counts[cat] < 150:
            if text not in ref_texts:
                ref_texts.append(text)
                ref_cats.append(cat)
                counts[cat] += 1

    model = _get_model()
    vecs = model.encode(ref_texts, show_progress_bar=False, batch_size=64)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    _ref_vecs = (vecs / norms).astype("float32")
    _ref_cats = ref_cats
    return len(ref_texts)


def knn_refine_batch(texts, rule_preds=None, k=7, threshold=0.70, demote_threshold=0.85):
    """批量向量复核。返回与 texts 等长的列表，元素为 (cat, sim) 或 None。

    安全约束（避免把闲聊误升级成交易而污染交易板）：
      - sell↔buy 内部纠偏：规则判为交易且 kNN 也判为交易时，采纳 kNN；
      - 高置信降级：kNN 判为 chat 且相似度 >= demote_threshold 时，允许把
        规则误判的交易降级为闲聊；
      - 其余方向（chat→sell/buy/notice 升级）一律不采纳。
    """
    import numpy as np
    if _ref_vecs is None or not len(texts):
        return [None] * len(texts)
    if rule_preds is None:
        rule_preds = [None] * len(texts)
    model = _get_model()
    vecs = model.encode(list(texts), show_progress_bar=False, batch_size=64)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vecs = (vecs / norms).astype("float32")
    sims = vecs @ _ref_vecs.T  # (n, ref)
    results = []
    for row, rp in zip(sims, rule_preds):
        idx = np.argsort(-row)[:k]
        votes = {}
        for i in idx:
            votes[_ref_cats[i]] = votes.get(_ref_cats[i], 0) + float(row[i])
        cat = max(votes, key=votes.get)
        top_sim = float(row[idx[0]])
        accept = False
        if top_sim >= threshold:
            if rp in ("sell", "buy") and cat in ("sell", "buy"):
                accept = True                      # 交易内部纠偏
            elif rp in ("sell", "buy") and cat == "chat" and top_sim >= demote_threshold:
                accept = True                      # 高置信降级
        results.append((cat, top_sim) if accept else None)
    return results
