"""
向量数据库模块（numpy版，不依赖chromadb）
- 为每条消息生成embedding向量
- 用numpy矩阵存储，余弦相似度检索
- 使用 bge-small-zh-v1.5 模型（95MB，中文效果好）
"""

import os
import json
import numpy as np
import threading

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_DIR = os.path.join(PROJECT_DIR, "messages", "vector_db")
DATA_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "ready_to_label.jsonl")

_model = None
_vectors = None       # numpy矩阵 (N, 512)
_messages = None      # 消息元数据列表
_lock = threading.Lock()


def get_model():
    """懒加载embedding模型"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        cache_dir = os.path.join(PROJECT_DIR, "models")
        print("[向量] 加载模型 BAAI/bge-small-zh-v1.5...")
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5", cache_folder=cache_dir)
        print("[向量] 模型加载完成")
    return _model


def build_vector_db(force=False):
    """
    构建向量数据库
    - 读取 ready_to_label.jsonl
    - 为每条消息生成embedding
    - 存为numpy矩阵和json元数据
    """
    global _vectors, _messages
    os.makedirs(VECTOR_DIR, exist_ok=True)
    
    vec_file = os.path.join(VECTOR_DIR, "vectors.npy")
    meta_file = os.path.join(VECTOR_DIR, "messages.json")
    
    # 已有数据且不强制重建
    if not force and os.path.exists(vec_file) and os.path.exists(meta_file):
        _load_db()
        print(f"[向量] 已有 {len(_messages)} 条向量数据，跳过构建")
        return len(_messages)
    
    # 读取消息
    if not os.path.exists(DATA_FILE):
        print(f"[向量] 数据文件不存在: {DATA_FILE}")
        return 0
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        msgs = [json.loads(line) for line in f if line.strip()]
    
    print(f"[向量] 开始为 {len(msgs)} 条消息生成embedding...")
    
    model = get_model()
    
    # 准备文本和元数据
    texts = []
    metas = []
    for i, m in enumerate(msgs):
        text = m.get("text", "")
        item = m.get("item_name", "")
        price = m.get("price", "")
        search_text = f"{text} {item} {price}".strip()
        if not search_text:
            search_text = "[无文本]"
        texts.append(search_text)
        metas.append({
            "index": i,
            "text": text[:200],
            "cat": m.get("category", "chat"),
            "item": item,
            "price": str(price) if price else "",
            "group_id": str(m.get("group_id", "")),
            "time": m.get("time_str", ""),
            "sender": m.get("sender_name", "")[:50],
        })
    
    # 批量生成embedding
    batch_size = 100
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vecs = model.encode(batch, show_progress_bar=False)
        all_vecs.append(vecs)
        print(f"[向量] 已处理 {min(i + batch_size, len(texts))}/{len(texts)}")
    
    vectors = np.vstack(all_vecs).astype(np.float32)
    
    # 归一化（这样点积=余弦相似度）
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors = vectors / norms
    
    # 保存
    np.save(vec_file, vectors)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False)
    
    # 加载到内存
    _vectors = vectors
    _messages = metas
    
    print(f"[向量] 构建完成，共 {len(metas)} 条")
    return len(metas)


def _load_db():
    """从文件加载向量库到内存"""
    global _vectors, _messages
    vec_file = os.path.join(VECTOR_DIR, "vectors.npy")
    meta_file = os.path.join(VECTOR_DIR, "messages.json")
    
    _vectors = np.load(vec_file)
    with open(meta_file, "r", encoding="utf-8") as f:
        _messages = json.load(f)
    
    # 确保归一化
    norms = np.linalg.norm(_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    _vectors = _vectors / norms


def search_semantic(query, top_k=20, cat_filter=None):
    """
    语义搜索
    - query: 用户搜索词
    - top_k: 返回前N条结果
    - cat_filter: 可选分类过滤
    - 返回: [{index, text, cat, item, price, score, ...}, ...]
    """
    with _lock:
        if _vectors is None or _messages is None:
            _load_db()
        
        if _vectors is None or len(_messages) == 0:
            return []
        
        model = get_model()
        query_vec = model.encode([query], show_progress_bar=False)
        # 归一化
        norm = np.linalg.norm(query_vec[0])
        if norm > 0:
            query_vec = query_vec / norm
        
        # 余弦相似度 = 归一化后的点积
        scores = _vectors @ query_vec[0]
        
        # 分类过滤
        if cat_filter and cat_filter != "all":
            mask = np.array([m["cat"] == cat_filter for m in _messages])
            scores = np.where(mask, scores, -1)
        
        # 取top_k
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.1:  # 太低的不返回
                break
            meta = _messages[idx]
            results.append({
                "index": meta["index"],
                "text": meta["text"],
                "cat": meta["cat"],
                "item": meta["item"],
                "price": meta["price"],
                "group_id": meta["group_id"],
                "time": meta["time"],
                "sender": meta["sender"],
                "score": round(score, 3),
            })
        
        return results


def match_subscription(query, msg_text, threshold=0.6):
    """
    语义订阅匹配
    - query: 订阅词（如"显示器"）
    - msg_text: 新消息文本
    - threshold: 相似度阈值
    - 返回: (命中bool, 相似度分数)
    """
    model = get_model()
    vecs = model.encode([query, msg_text], show_progress_bar=False)
    # 归一化
    v0 = vecs[0] / (np.linalg.norm(vecs[0]) + 1e-8)
    v1 = vecs[1] / (np.linalg.norm(vecs[1]) + 1e-8)
    sim = float(np.dot(v0, v1))
    return (sim >= threshold, sim)


def get_status():
    """获取向量数据库状态"""
    try:
        if _vectors is None or _messages is None:
            _load_db()
        return {"ready": True, "count": len(_messages)}
    except Exception:
        return {"ready": False, "count": 0}


if __name__ == "__main__":
    count = build_vector_db(force=True)
    print(f"\n向量库构建完成，共 {count} 条")
    
    print("\n--- 语义搜索测试 ---")
    for query in ["代步工具", "显示器", "便宜的家具", "自行车", "书本教材"]:
        print(f"\n搜索: {query}")
        results = search_semantic(query, top_k=5)
        for r in results:
            print(f"  [{r['score']:.3f}] {r['text'][:40]}  ({r['cat']})")
