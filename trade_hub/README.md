# 淘物集市 · 二手交易群信息聚合系统

把二手交易群里每天数百条杂乱消息，自动变成 **可搜索、可筛选、可视化、可一键联系卖家** 的商品集市。

## 系统架构

```
QQ 群消息
   │  NapCat (OneBot WebSocket)
   ▼
push_notify/run.py          实时采集（文本+图片+OCR）→ messages/raw/
   │  push_notify/preprocess.py   消息合并 / OCR / 实体提取
   ▼
messages/labeled/ready_to_label.jsonl        （2800+ 条真实群消息）
   │
   ▼
trade_hub/pipeline/build_site.py   本项目核心管线
   ├─ classifier.py     意图分类（规则 + bge-small-zh 向量 kNN 安全复核）
   │                    商品类别分类（9 大类关键词计分）
   ├─ authenticity.py   同用户重发合并 / 跨用户重复标记 / 广告识别 / 可信度评分
   └─ 缩略图生成 + 统计聚合 → dist/（纯静态站点）
   │
   ▼
trade_hub/web/            零依赖响应式 PWA 前端
   手机 / 平板 / 电脑自适应，可安装到桌面，弱网离线可用
```

## 快速开始

```bash
# 一键构建 + 启动（默认 http://localhost:8642）
python serve.py

# 更快的构建（跳过向量复核，纯规则准确率已达 99.2%）
python serve.py --no-knn

# 只启动不重新构建
python serve.py --no-build
```

依赖：Python 3.10+，`pillow`（缩略图）；可选 `sentence-transformers`（向量复核，缺失时自动退回纯规则）。

## 功能对照

| 目标 | 实现 |
|---|---|
| 消息采集 | 保留 push_notify 的 NapCat 实时采集链路；serve.py 检测到新 raw 数据自动重新预处理 |
| 分类准确率 | 意图分类 **99.2%**（125 条人工复核困难样本）；规则高置信直判 + 向量 kNN 仅做安全方向纠偏 |
| 数据真实性 | 广告关键词识别、外链/异常价格标记、同用户重发合并（26 条）、跨用户重复标记、0-100 可信度评分；默认只展示可信条目 |
| 搜索 | 关键词 + 26 组同义词扩展（"电动车"可搜出"小电驴"），多词 AND、组内 OR，220ms 防抖 |
| 跨设备访问 | 响应式布局（2 列手机 / 3-4 列桌面）+ PWA 可安装 + Service Worker 离线缓存；可部署公网 |
| UI | 卡片流集市、详情弹层、图片灯箱、绿色主题、骨架空态 |
| 可视化报表 | 消息量趋势、热门类别、供需环形图、价格中位数、热搜词云、群活跃度（手写 SVG，零依赖无 CDN） |
| 一键联系 | 复制 QQ/微信/手机号 + 移动端唤起 QQ 临时会话（mqqwpa://）/ 桌面端 tencent:// 协议 / tel: 拨号 |
| 鲁棒性 | 数据加载失败兜底、图片加载失败占位、剪贴板双重降级、全局错误捕获、构建失败保留旧版本 |

## 目录说明

```
trade_hub/
├─ pipeline/
│  ├─ config.py        分类体系 / 同义词 / 广告规则等全部配置
│  ├─ classifier.py    意图 + 商品类别分类器
│  ├─ authenticity.py  去重与真实性评估
│  ├─ build_site.py    主构建管线
│  └─ evaluate.py      准确率评估（vs 人工标注）
├─ web/                前端源码（原生 HTML/CSS/JS，零依赖）
├─ dist/               构建产物（静态站点，可直接部署任意静态托管）
├─ serve.py            一键启动
└─ README.md
```

## 分类准确率评估

```bash
python pipeline/evaluate.py          # 规则 + kNN
python pipeline/evaluate.py --no-knn # 仅规则
```

测试集为 `manual_labels.jsonl` 中 125 条人工复核样本（全部是规则最难判的可疑样本，
实际线上整体准确率高于此值）。当前：纯规则 99.2%，+kNN 保持 99.2%（kNN 仅在
sell↔buy 纠偏与高置信降级两个安全方向生效，杜绝把闲聊误升级为交易）。

## 实时采集（可选）

需要 Windows + QQ + NapCat：

1. `push_notify/start_napcat.bat` 启动 NapCat（WebSocket 3001）
2. `python push_notify/run.py` 持续采集群消息
3. 重跑 `python serve.py`，新消息自动进入站点
