"""
疑点检测：找出被误判为闲聊的交易消息
- 对每条闲聊消息，和所有出售/求购消息算最大相似度
- 相似度高的 = 疑似误判
"""
import os
import json
import numpy as np
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vector_db import get_model, build_vector_db

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "ready_to_label.jsonl")
OUTPUT_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "suspicious_chat.jsonl")

def detect_suspicious():
    # 确保向量库已构建
    build_vector_db()
    
    # 读取消息
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        msgs = [json.loads(line) for line in f if line.strip()]
    
    # 分离闲聊和交易消息
    chat_msgs = [m for m in msgs if m.get("category") == "chat"]
    trade_msgs = [m for m in msgs if m.get("category") in ("sell", "buy")]
    
    print(f"闲聊消息: {len(chat_msgs)} 条")
    print(f"交易消息: {len(trade_msgs)} 条 (用于相似度对比)")
    
    model = get_model()
    
    # 为所有交易消息生成embedding
    print("生成交易消息embedding...")
    trade_texts = []
    for m in trade_msgs:
        text = f"{m.get('text', '')} {m.get('item_name', '')} {m.get('price', '')}".strip()
        if not text:
            text = "[无文本]"
        trade_texts.append(text)
    
    trade_vecs = model.encode(trade_texts, show_progress_bar=False, batch_size=100)
    # 归一化
    trade_norms = np.linalg.norm(trade_vecs, axis=1, keepdims=True)
    trade_norms[trade_norms == 0] = 1
    trade_vecs = trade_vecs / trade_norms
    
    # 为每条闲聊消息算和交易消息的最大相似度
    print(f"\n检测 {len(chat_msgs)} 条闲聊消息...")
    suspicious = []
    
    batch_size = 50
    for i in range(0, len(chat_msgs), batch_size):
        batch = chat_msgs[i:i + batch_size]
        batch_texts = []
        for m in batch:
            text = f"{m.get('text', '')} {m.get('item_name', '')} {m.get('price', '')}".strip()
            if not text:
                text = "[无文本]"
            batch_texts.append(text)
        
        # 生成embedding
        batch_vecs = model.encode(batch_texts, show_progress_bar=False)
        batch_norms = np.linalg.norm(batch_vecs, axis=1, keepdims=True)
        batch_norms[batch_norms == 0] = 1
        batch_vecs = batch_vecs / batch_norms
        
        # 算每条闲聊和所有交易消息的相似度
        sim_matrix = batch_vecs @ trade_vecs.T  # (batch, trade)
        
        for j, m in enumerate(batch):
            max_sell_sim = 0
            max_buy_sim = 0
            best_sell_text = ""
            best_buy_text = ""
            
            for k, tm in enumerate(trade_msgs):
                sim = float(sim_matrix[j][k])
                if tm["category"] == "sell" and sim > max_sell_sim:
                    max_sell_sim = sim
                    best_sell_text = tm.get("text", "")[:50]
                elif tm["category"] == "buy" and sim > max_buy_sim:
                    max_buy_sim = sim
                    best_buy_text = tm.get("text", "")[:50]
            
            max_sim = max(max_sell_sim, max_buy_sim)
            suspected_cat = "sell" if max_sell_sim > max_buy_sim else "buy"
            best_match = best_sell_text if suspected_cat == "sell" else best_buy_text
            
            # 只保留相似度>0.65的可疑消息
            if max_sim > 0.65:
                suspicious.append({
                    "text": m.get("text", "")[:200],
                    "current_cat": "chat",
                    "suspected_cat": suspected_cat,
                    "similarity": round(max_sim, 3),
                    "best_match": best_match,
                    "group_id": str(m.get("group_id", "")),
                    "time": m.get("time_str", ""),
                    "has_image": m.get("has_image", False),
                    "image_count": m.get("image_count", 0),
                })
        
        print(f"  已检测 {min(i + batch_size, len(chat_msgs))}/{len(chat_msgs)}")
    
    # 按相似度排序
    suspicious.sort(key=lambda x: x["similarity"], reverse=True)
    
    # 保存
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for s in suspicious:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    print(f"\n检测完成！")
    print(f"可疑消息: {len(suspicious)} 条 (相似度>0.5)")
    print(f"已保存到: {OUTPUT_FILE}")
    
    # 打印前20条
    print(f"\n--- 前20条最可疑的消息 ---")
    for i, s in enumerate(suspicious[:20]):
        print(f"\n{i+1}. [{s['similarity']:.3f}] 疑似{s['suspected_cat']}")
        print(f"   消息: {s['text'][:60]}")
        print(f"   对比: {s['best_match']}")
        if s["has_image"]:
            print(f"   有图片: {s['image_count']}张")


if __name__ == "__main__":
    detect_suspicious()
