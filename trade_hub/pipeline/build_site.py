# -*- coding: utf-8 -*-
"""主构建管线：
  加载 push_notify 预处理数据 → 意图复核(规则+向量) → 商品类别分类
  → 去重 → 真实性评估 → 缩略图生成 → 统计聚合 → 输出静态站点 dist/
用法：
  python build_site.py            # 完整构建（含缩略图）
  python build_site.py --no-knn   # 跳过向量复核（无 sentence-transformers 时）
  python build_site.py --no-thumbs
"""
import os
import sys
import json
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DATA_FILE, IMAGES_DIR, WEB_DIR, DIST_DIR, DIST_DATA_DIR, DIST_THUMBS_DIR,
    THUMB_MAX_SIZE, THUMB_QUALITY, CATEGORY_NAMES, SYNONYM_MAP,
)
from classifier import (
    classify_intent_rule, classify_category, extract_prices,
    build_knn_reference, knn_refine_batch,
)
from authenticity import detect_duplicates, assess_authenticity


def log(msg):
    print(f"[build] {msg}", flush=True)


def load_messages():
    msgs = []
    with open(DATA_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                msgs.append(json.loads(line))
    log(f"加载消息 {len(msgs)} 条")
    return msgs


def refine_intents(msgs, use_knn=True):
    """重新分类意图：规则高置信直接用；低置信用向量 kNN 复核"""
    results = []
    low_idx = []
    for i, m in enumerate(msgs):
        text = m.get("text") or ""
        ocr = " ".join(m.get("ocr_texts") or [])
        full = (text + " " + ocr).strip()
        cat, conf = classify_intent_rule(full, m.get("has_image"))
        # OCR 已人工确认的分类优先
        if m.get("ocr_confirmed") and m.get("category") in ("sell", "buy", "chat", "notice"):
            cat, conf = m["category"], "high"
        results.append(cat)
        if conf == "low":
            low_idx.append(i)

    knn_used = 0
    if use_knn and low_idx:
        try:
            n_ref = build_knn_reference(msgs)
            log(f"kNN 参考库 {n_ref} 条，低置信消息 {len(low_idx)} 条待复核")
            texts = [(msgs[i].get("text") or "") + " " + " ".join(msgs[i].get("ocr_texts") or []) for i in low_idx]
            refined = knn_refine_batch(texts, rule_preds=[results[i] for i in low_idx])
            for i, r in zip(low_idx, refined):
                if r is not None:
                    cat, sim = r
                    if cat != results[i]:
                        knn_used += 1
                    results[i] = cat
            log(f"kNN 复核完成，修正 {knn_used} 条")
        except Exception as e:
            log(f"kNN 不可用，退回纯规则: {e}")
    return results


def make_title(text, max_len=32):
    t = (text or "").strip().replace("\n", " ")
    t = " ".join(t.split())
    return t[:max_len] + ("…" if len(t) > max_len else "")


def resolve_image(group_id, path):
    """把数据中的图片路径解析为本地文件"""
    if not path:
        return None
    base = os.path.basename(path.replace("\\", "/"))
    candidate = os.path.join(IMAGES_DIR, str(group_id), base)
    if os.path.exists(candidate):
        return candidate
    # 兜底：全局搜一层
    for gid in os.listdir(IMAGES_DIR):
        p = os.path.join(IMAGES_DIR, gid, base)
        if os.path.exists(p):
            return p
    return None


def build_thumbnails(items, enable=True):
    """为交易消息生成压缩缩略图，返回 {本地路径: web相对路径}"""
    os.makedirs(DIST_THUMBS_DIR, exist_ok=True)
    mapping = {}
    if not enable:
        return mapping
    try:
        from PIL import Image
    except ImportError:
        log("Pillow 未安装，跳过缩略图")
        return mapping

    todo = []
    for it in items:
        for local in it["_local_images"]:
            if local and local not in mapping:
                todo.append(local)
                mapping[local] = None

    log(f"生成缩略图 {len(todo)} 张…")
    done = 0
    for local in todo:
        try:
            gid = os.path.basename(os.path.dirname(local))
            name = os.path.splitext(os.path.basename(local))[0] + ".jpg"
            out_dir = os.path.join(DIST_THUMBS_DIR, gid)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, name)
            rel = f"thumbs/{gid}/{name}"
            if not os.path.exists(out_path):
                with Image.open(local) as im:
                    im = im.convert("RGB")
                    im.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE))
                    im.save(out_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
            mapping[local] = rel
            done += 1
        except Exception:
            mapping[local] = None
    log(f"缩略图完成 {done}/{len(todo)}")
    return mapping


def main():
    t0 = time.time()
    use_knn = "--no-knn" not in sys.argv
    use_thumbs = "--no-thumbs" not in sys.argv

    msgs = load_messages()
    intents = refine_intents(msgs, use_knn=use_knn)

    # ---- 组装条目 ----
    all_dates = Counter()      # 全部消息日趋势
    trade_dates = Counter()    # 交易消息日趋势
    intent_count = Counter()

    items = []
    for m, intent in zip(msgs, intents):
        intent_count[intent] += 1
        date = (m.get("time_str") or "")[:10]
        if date:
            all_dates[date] += 1

        if intent not in ("sell", "buy"):
            continue
        if date:
            trade_dates[date] += 1

        text = m.get("text") or ""
        ocr = " ".join(m.get("ocr_texts") or [])
        prices = extract_prices(text) or extract_prices(ocr)
        cat = classify_category(text, ocr)
        ci = m.get("contact_info") or {}
        contact = {
            "qq": ci.get("qq") or str(m.get("user_id") or ""),
            "wechat": ci.get("wechat") or "",
            "phone": ci.get("phone") or "",
        }
        local_images = [resolve_image(m.get("group_id"), p) for p in (m.get("image_paths") or [])]
        local_images = [p for p in local_images if p][:6]

        items.append({
            "id": str(m.get("first_message_id")),
            "type": intent,                      # sell / buy
            "cat": cat,                          # 商品类别 id
            "title": make_title(text or ocr or "（图片消息）"),
            "text": text,
            "ocr_text": ocr,
            "price": prices[0] if prices else None,
            "prices": prices,
            "cond": (m.get("entities") or {}).get("conditions") or [],
            "contact": contact,
            "user_id": str(m.get("user_id") or ""),
            "nick": m.get("card") or m.get("nickname") or "匿名",
            "group": m.get("group_name") or str(m.get("group_id")),
            "group_id": str(m.get("group_id") or ""),
            "time": m.get("time") or 0,
            "time_str": m.get("time_str") or "",
            "_local_images": local_images,
        })

    log(f"意图分布: {dict(intent_count)}")
    log(f"交易消息 {len(items)} 条")

    # ---- 去重 ----
    before = len(items)
    items = detect_duplicates(items)
    log(f"去重: {before} → {len(items)}（合并重发 {before - len(items)} 条）")

    # ---- 真实性 ----
    level_count = Counter()
    for it in items:
        flags, score, level = assess_authenticity(it)
        it["flags"] = flags
        it["trust"] = score
        it["level"] = level
        level_count[level] += 1
    log(f"真实性: {dict(level_count)}")

    # ---- 缩略图 ----
    thumb_map = build_thumbnails(items, enable=use_thumbs)
    for it in items:
        it["images"] = [thumb_map.get(p) for p in it["_local_images"]]
        it["images"] = [x for x in it["images"] if x]
        del it["_local_images"]

    items.sort(key=lambda x: -x["time"])

    # ---- 统计 ----
    cat_counter = Counter(it["cat"] for it in items)
    group_counter = Counter()
    group_trade = defaultdict(lambda: {"sell": 0, "buy": 0})
    price_by_cat = defaultdict(list)
    kw_counter = Counter()
    for it in items:
        group_counter[it["group"]] += 1
        group_trade[it["group"]][it["type"]] += 1
        if it["price"] and 1 <= it["price"] <= 20000:
            price_by_cat[it["cat"]].append(it["price"])
        for kw, syns in SYNONYM_MAP.items():
            t = (it["text"] + it["ocr_text"]).lower()
            if kw.lower() in t or any(s.lower() in t for s in syns):
                kw_counter[kw] += 1

    def med(lst):
        s = sorted(lst)
        return s[len(s) // 2] if s else None

    stats = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_raw": len(msgs),
        "total_trade": len(items),
        "intent": dict(intent_count),
        "levels": dict(level_count),
        "dup_merged": before - len(items),
        "trend_all": sorted(all_dates.items()),
        "trend_trade": sorted(trade_dates.items()),
        "categories": [
            {"id": cid, "name": CATEGORY_NAMES[cid], "count": cat_counter.get(cid, 0)}
            for cid in CATEGORY_NAMES if cat_counter.get(cid, 0) > 0
        ],
        "groups": [
            {"name": g, "count": c, **group_trade[g]}
            for g, c in group_counter.most_common()
        ],
        "price_median": {
            cid: {"median": med(v), "n": len(v)}
            for cid, v in price_by_cat.items() if len(v) >= 3
        },
        "hot_keywords": kw_counter.most_common(15),
    }

    # ---- 输出 ----
    os.makedirs(DIST_DATA_DIR, exist_ok=True)
    with open(os.path.join(DIST_DATA_DIR, "items.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DIST_DATA_DIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DIST_DATA_DIR, "synonyms.json"), "w", encoding="utf-8") as f:
        json.dump(SYNONYM_MAP, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DIST_DATA_DIR, "categories.json"), "w", encoding="utf-8") as f:
        json.dump(CATEGORY_NAMES, f, ensure_ascii=False)

    # 拷贝前端
    if os.path.isdir(WEB_DIR):
        for name in os.listdir(WEB_DIR):
            src = os.path.join(WEB_DIR, name)
            dst = os.path.join(DIST_DIR, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    size_mb = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(DIST_DIR) for fn in fns
    ) / 1024 / 1024
    log(f"构建完成 → {DIST_DIR}（{size_mb:.1f} MB，耗时 {time.time()-t0:.1f}s）")


if __name__ == "__main__":
    main()
