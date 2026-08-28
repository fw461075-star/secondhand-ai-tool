# -*- coding: utf-8 -*-
"""分类准确率评估：
  用 manual_labels.jsonl（人工标注）作为测试集，
  评估 规则 与 规则+kNN 两种方案的意图分类准确率。
用法：
  python evaluate.py            # 规则 + kNN
  python evaluate.py --no-knn   # 仅规则
"""
import sys
import os
import json
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MANUAL_LABELS_FILE, DATA_FILE
from classifier import classify_intent_rule, build_knn_reference, knn_refine_batch


def load_testset():
    """人工复核记录 → (text, gold_label) 列表。
    字段语义：original_cat=原分类，suspected_cat=可疑目标类。
      label="correct"  → 原分类正确，gold=original_cat
      label=sell/buy/chat → 人工改判，gold=label
      label="invalid"  → 无效样本，跳过
    """
    tests = []
    with open(MANUAL_LABELS_FILE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            label = d.get("label")
            if label in ("sell", "buy", "chat", "notice"):
                tests.append((d["text"], label))
            elif label == "correct" and d.get("original_cat") in ("sell", "buy", "chat", "notice"):
                tests.append((d["text"], d["original_cat"]))
    return tests


def main():
    use_knn = "--no-knn" not in sys.argv
    tests = load_testset()
    print(f"测试集 {len(tests)} 条（人工标注）")

    # 规则预测
    preds, confs = [], []
    for text, _ in tests:
        cat, conf = classify_intent_rule(text)
        preds.append(cat)
        confs.append(conf)

    def report(name, preds):
        correct = sum(1 for (_, g), p in zip(tests, preds) if g == p)
        acc = correct / len(tests) * 100
        print(f"\n== {name}: 准确率 {acc:.1f}% ({correct}/{len(tests)}) ==")
        # 混淆矩阵
        conf_mat = defaultdict(Counter)
        for (_, g), p in zip(tests, preds):
            conf_mat[g][p] += 1
        cats = ["sell", "buy", "notice", "chat"]
        print("gold\\pred " + " ".join(f"{c:>6}" for c in cats))
        for g in cats:
            if conf_mat[g]:
                print(f"{g:>9} " + " ".join(f"{conf_mat[g].get(c,0):>6}" for c in cats))
        # 每类 P/R
        for c in cats:
            tp = conf_mat[c].get(c, 0)
            fn = sum(conf_mat[c].values()) - tp
            fp = sum(conf_mat[g].get(c, 0) for g in conf_mat if g != c)
            if tp + fn == 0:
                continue
            p = tp / (tp + fp) * 100 if tp + fp else 0
            r = tp / (tp + fn) * 100
            print(f"  {c}: P={p:.0f}% R={r:.0f}% (n={tp+fn})")
        return acc

    acc_rule = report("纯规则", preds)

    if use_knn:
        # 排除测试集文本，避免泄漏
        msgs = []
        test_texts = {t for t, _ in tests}
        with open(DATA_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    if (m.get("text") or "") not in test_texts:
                        msgs.append(m)
        n_ref = build_knn_reference(msgs)
        print(f"\nkNN 参考库 {n_ref} 条（已排除测试集文本防泄漏）")

        low_idx = [i for i, c in enumerate(confs) if c == "low"]
        refined = knn_refine_batch(
            [tests[i][0] for i in low_idx],
            rule_preds=[preds[i] for i in low_idx],
        )
        preds2 = list(preds)
        changed = 0
        for i, r in zip(low_idx, refined):
            if r is not None and r[0] != preds2[i]:
                preds2[i] = r[0]
                changed += 1
        print(f"低置信 {len(low_idx)} 条，kNN 修正 {changed} 条")
        acc_knn = report("规则 + kNN 复核", preds2)
        print(f"\n提升: {acc_knn - acc_rule:+.1f}pp")

        # 打印仍分错的样本，便于迭代规则
        print("\n---- 仍错分样本（前15条）----")
        shown = 0
        for (t, g), p in zip(tests, preds2):
            if g != p and shown < 15:
                print(f"[gold={g} pred={p}] {t[:60]!r}")
                shown += 1


if __name__ == "__main__":
    main()
