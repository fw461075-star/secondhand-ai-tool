"""
kNN分类器模块
- 用标注数据和现有交易消息作为参考库
- 当关键词分类不确定时，用embedding相似度找最相似的参考样本
- 零成本，全部本地计算
"""
import os
import json
import numpy as np
import threading

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "manual_labels.jsonl")
DATA_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "ready_to_label.jsonl")

# 从标注数据中提取的新关键词
NEW_SELL_KEYWORDS = ["送", "有要的", "来拿", "自提", "自取"]
NEW_BUY_KEYWORDS = ["蹲", "有偿借用", "还在吗", "代课", "借用"]

# kNN参考库
_ref_texts = None
_ref_cats = None
_ref_vecs = None
_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        cache_dir = os.path.join(PROJECT_DIR, "models")
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5", cache_folder=cache_dir)
    return _model


def build_reference():
    """构建kNN参考库：标注数据 + 现有交易消息"""
    global _ref_texts, _ref_cats, _ref_vecs

    if _ref_texts is not None:
        return

    with _lock:
        if _ref_texts is not None:
            return

        ref_texts = []
        ref_cats = []

        # 1. 加载标注数据
        if os.path.exists(LABELS_FILE):
            with open(LABELS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        label = d["label"]
                        if label in ("sell", "buy", "chat"):
                            ref_texts.append(d["text"])
                            ref_cats.append(label)

        # 2. 加载已确认的OCR数据（用户确认过分类的OCR消息）
        CONFIRMED_OCR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages", "labeled", "confirmed_ocr.json")
        if os.path.exists(CONFIRMED_OCR_FILE):
            try:
                with open(CONFIRMED_OCR_FILE, "r", encoding="utf-8") as f:
                    confirmed = json.load(f)
                # 格式: ["msg_id:cat", ...]
                for entry in confirmed:
                    if ":" in entry:
                        mid, cat = entry.rsplit(":", 1)
                        if cat in ("sell", "buy", "chat"):
                            # 从数据文件中找到对应消息的OCR文字
                            if os.path.exists(DATA_FILE):
                                with open(DATA_FILE, "r", encoding="utf-8") as df:
                                    for line in df:
                                        if line.strip():
                                            m = json.loads(line)
                                            if m.get("message_ids", [None])[0] == mid:
                                                ocr_text = " ".join(m.get("ocr_texts", []))
                                                if ocr_text and ocr_text not in ref_texts:
                                                    ref_texts.append(ocr_text)
                                                    ref_cats.append(cat)
                                                break
            except:
                pass

        # 3. 加载现有交易消息（出售/求购各取100条作为参考）
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                msgs = [json.loads(l) for l in f if l.strip()]

            sell_msgs = [m for m in msgs if m.get("category") == "sell"][:100]
            buy_msgs = [m for m in msgs if m.get("category") == "buy"][:100]

            for m in sell_msgs:
                text = m.get("text", "")
                if text and text not in ref_texts:
                    ref_texts.append(text)
                    ref_cats.append("sell")

            for m in buy_msgs:
                text = m.get("text", "")
                if text and text not in ref_texts:
                    ref_texts.append(text)
                    ref_cats.append("buy")

        # 3. 生成embedding
        if ref_texts:
            model = get_model()
            vecs = model.encode(ref_texts, show_progress_bar=False, batch_size=100)
            # 归一化
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1
            vecs = vecs / norms

            _ref_texts = ref_texts
            _ref_cats = ref_cats
            _ref_vecs = vecs.astype(np.float32)

            print(f"[kNN] 参考库构建完成: {len(ref_texts)} 条")
        else:
            _ref_texts = []
            _ref_cats = []
            _ref_vecs = np.array([])


def batch_knn_classify(texts, k=5, confidence_threshold=0.7):
    """
    批量kNN分类（解决逐条调用卡死的问题）
    一次性编码所有文本，然后逐条匹配
    
    参数:
        texts: ["文本1", "文本2", ...]
        k: top-k参考样本
        confidence_threshold: 置信度阈值，低于此值返回"chat"
    
    返回: ["sell", "buy", "chat", ...]  与texts等长
    """
    if not texts:
        return []
    
    build_reference()
    
    if _ref_vecs is None or len(_ref_texts) == 0:
        return ["chat"] * len(texts)
    
    model = get_model()
    
    # 批量编码所有文本（关键优化：一次encode，不是逐条）
    print(f"[kNN] 批量编码 {len(texts)} 条文本...")
    query_vecs = model.encode(texts, show_progress_bar=True, batch_size=64)
    
    # 归一化
    norms = np.linalg.norm(query_vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    query_vecs = query_vecs / norms
    
    # 批量计算余弦相似度 (N x M矩阵)
    scores_matrix = query_vecs @ _ref_vecs.T  # (N, M)
    
    results = []
    for i in range(len(texts)):
        scores = scores_matrix[i]
        
        # 取top_k
        kk = min(k, len(scores))
        top_indices = np.argsort(scores)[::-1][:kk]
        
        # 加权投票
        votes = {}
        for idx in top_indices:
            cat = _ref_cats[idx]
            score = float(scores[idx])
            votes[cat] = votes.get(cat, 0) + score
        
        if not votes:
            results.append("chat")
            continue
        
        best_cat = max(votes, key=votes.get)
        total = sum(votes.values())
        confidence = votes[best_cat] / total if total > 0 else 0
        
        if confidence >= confidence_threshold:
            results.append(best_cat)
        else:
            results.append("chat")
    
    return results


def knn_classify(text, k=5):
    """
    kNN分类：找最相似的k条参考消息，投票决定分类
    返回: (分类, 置信度)
    """
    build_reference()

    if _ref_vecs is None or len(_ref_texts) == 0:
        return None, 0

    model = get_model()
    query_vec = model.encode([text], show_progress_bar=False)
    norm = np.linalg.norm(query_vec[0])
    if norm > 0:
        query_vec = query_vec / norm

    # 余弦相似度
    scores = _ref_vecs @ query_vec[0]

    # 取top_k
    k = min(k, len(scores))
    top_indices = np.argsort(scores)[::-1][:k]

    # 投票
    votes = {}
    for idx in top_indices:
        cat = _ref_cats[idx]
        score = float(scores[idx])
        votes[cat] = votes.get(cat, 0) + score

    # 加权投票（按相似度加权）
    best_cat = max(votes, key=votes.get)
    total = sum(votes.values())
    confidence = votes[best_cat] / total if total > 0 else 0

    return best_cat, round(confidence, 3)


def classify_with_knn(text, has_image=False):
    """
    混合分类：关键词优先，关键词没命中时用kNN
    """
    from preprocess import SELL_KEYWORDS, BUY_KEYWORDS, NOTICE_KEYWORDS, PRICE_KEYWORDS, classify_intent

    # 第1层：原有关键词分类
    cat = classify_intent(text, has_image)
    if cat != "chat":
        return cat

    # 第2层：新关键词（从标注数据提取）
    for kw in NEW_SELL_KEYWORDS:
        if kw in text:
            return "sell"
    for kw in NEW_BUY_KEYWORDS:
        if kw in text:
            return "buy"

    # 第3层：kNN分类
    # 跳过条件：文本太短（<4字）且没图片 → kNN对短文本不可靠
    if len(text.strip()) < 4 and not has_image:
        return "chat"

    knn_cat, confidence = knn_classify(text)
    # 阈值提高到0.7，降低误判率
    if knn_cat and confidence > 0.7:
        return knn_cat

    return "chat"


if __name__ == "__main__":
    # 测试
    build_reference()

    print("\n--- kNN分类测试 ---")
    test_cases = [
        "蹲蹲烘干机会员",
        "送两个挂篮和一个床边架，海八自取",
        "送包花材料和鲜花干燥剂，海8自提，要的话@我",
        "暑假有偿借用一张一卡通",
        "接双创周代课",
        "冰箱还在吗",
        "退宿领完双证之后还能进宿舍吗？",
        "杭研币咋也花不了了",
        "哈哈哈",
        "出显示器50r",
        "收个自行车",
        "蹲安大电瓶车校园牌",
        "2-636这边有椅子和外置散热器一些日用品什么的有要的可以自己来拿",
        "送四六级听力耳机 梧桐苑附近自取",
    ]

    for text in test_cases:
        cat = classify_with_knn(text)
        knn_cat, conf = knn_classify(text)
        print(f"  [{cat:5s}] (kNN:{knn_cat}/{conf}) {text[:40]}")
