"""
标注服务器：提供标注页面和API
"""
import os
import json
import http.server
import urllib.parse

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SUSPICIOUS_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "suspicious_chat.jsonl")
LABELS_FILE = os.path.join(PROJECT_DIR, "messages", "labeled", "manual_labels.jsonl")

PORT = 8766

def load_suspicious():
    if not os.path.exists(SUSPICIOUS_FILE):
        return []
    with open(SUSPICIOUS_FILE, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def load_labels():
    if not os.path.exists(LABELS_FILE):
        return {}
    labels = {}
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                labels[d["text"]] = d
    return labels

def save_label(text, label, original_cat, suspected_cat):
    labels = load_labels()
    labels[text] = {
        "text": text,
        "label": label,
        "original_cat": original_cat,
        "suspected_cat": suspected_cat,
    }
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        for v in labels.values():
            f.write(json.dumps(v, ensure_ascii=False) + "\n")

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据标注 - 二手交易助手</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background:#f5f5f5; color:#333; }
.header { background:#fff; padding:12px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.1); position:sticky; top:0; z-index:10; }
.header h1 { font-size:18px; }
.stats { font-size:13px; color:#666; margin-top:4px; }
.progress-bar { height:6px; background:#e0e0e0; border-radius:3px; margin-top:8px; overflow:hidden; }
.progress-fill { height:100%; background:#4CAF50; transition:width 0.3s; }
.list { max-width:700px; margin:0 auto; padding:16px; }
.card { background:#fff; border-radius:8px; padding:16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
.card.labeled { opacity:0.5; }
.card.labeled .text { text-decoration:line-through; }
.sim-badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; color:#fff; margin-bottom:8px; }
.sim-sell { background:#4CAF50; }
.sim-buy { background:#FF9800; }
.text { font-size:15px; line-height:1.5; margin-bottom:8px; word-break:break-all; }
.match { font-size:12px; color:#888; margin-bottom:12px; }
.match b { color:#555; }
.img-info { font-size:12px; color:#999; margin-bottom:8px; }
.btn-group { display:flex; gap:8px; flex-wrap:wrap; }
.btn { padding:6px 14px; border:none; border-radius:4px; cursor:pointer; font-size:13px; transition:all 0.2s; }
.btn:hover { transform:translateY(-1px); box-shadow:0 2px 4px rgba(0,0,0,0.15); }
.btn-correct { background:#4CAF50; color:#fff; }
.btn-sell { background:#2196F3; color:#fff; }
.btn-buy { background:#FF9800; color:#fff; }
.btn-chat { background:#9E9E9E; color:#fff; }
.btn-invalid { background:#f44336; color:#fff; }
.btn-skip { background:#e0e0e0; color:#666; }
.label-tag { display:inline-block; padding:2px 8px; border-radius:3px; font-size:11px; color:#fff; margin-left:8px; }
.filter-bar { margin-bottom:12px; display:flex; gap:8px; flex-wrap:wrap; }
.filter-btn { padding:4px 12px; border:1px solid #ddd; background:#fff; border-radius:4px; cursor:pointer; font-size:13px; }
.filter-btn.active { background:#333; color:#fff; border-color:#333; }
</style>
</head>
<body>

<div class="header">
  <h1>数据标注 - 可疑闲聊消息</h1>
  <div class="stats" id="stats">加载中...</div>
  <div class="progress-bar"><div class="progress-fill" id="progress" style="width:0%"></div></div>
</div>

<div class="list">
  <div class="filter-bar">
    <button class="filter-btn active" onclick="setFilter('all', this)">全部</button>
    <button class="filter-btn" onclick="setFilter('unlabeled', this)">待标注</button>
    <button class="filter-btn" onclick="setFilter('labeled', this)">已标注</button>
    <button class="filter-btn" onclick="setFilter('has_image', this)">有图片</button>
  </div>
  <div id="cardList"></div>
</div>

<script>
let allData = [];
let labels = {};
let currentFilter = 'all';

async function loadData() {
  const resp = await fetch('/api/data');
  const data = await resp.json();
  allData = data.suspicious;
  labels = data.labels;
  render();
}

function setFilter(f, btn) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  render();
}

function render() {
  const list = document.getElementById('cardList');
  let shown = allData;
  
  if (currentFilter === 'unlabeled') {
    shown = allData.filter(d => !labels[d.text]);
  } else if (currentFilter === 'labeled') {
    shown = allData.filter(d => labels[d.text]);
  } else if (currentFilter === 'has_image') {
    shown = allData.filter(d => d.has_image);
  }
  
  // 统计
  const total = allData.length;
  const labeled = allData.filter(d => labels[d.text]).length;
  const pct = total > 0 ? (labeled / total * 100).toFixed(1) : 0;
  document.getElementById('stats').textContent = `已标注 ${labeled}/${total} 条 (${pct}%)`;
  document.getElementById('progress').style.width = pct + '%';
  
  if (shown.length === 0) {
    list.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">没有数据</div>';
    return;
  }
  
  let html = '';
  for (let i = 0; i < shown.length; i++) {
    const d = shown[i];
    const labeled = labels[d.text];
    const cls = labeled ? 'card labeled' : 'card';
    const simClass = d.suspected_cat === 'sell' ? 'sim-sell' : 'sim-buy';
    const catText = d.suspected_cat === 'sell' ? '疑似出售' : '疑似求购';
    
    html += `<div class="${cls}" id="card-${i}">`;
    html += `<span class="sim-badge ${simClass}">${catText} ${d.similarity}</span>`;
    if (labeled) {
      const labelMap = {'correct':'正确','sell':'→出售','buy':'→求购','chat':'→闲聊','invalid':'无效'};
      const labelColor = {'correct':'#4CAF50','sell':'#2196F3','buy':'#FF9800','chat':'#9E9E9E','invalid':'#f44336'};
      html += `<span class="label-tag" style="background:${labelColor[labeled.label]}">${labelMap[labeled.label]}</span>`;
    }
    html += `<div class="text">${escapeHtml(d.text)}</div>`;
    if (d.has_image) {
      html += `<div class="img-info">📷 ${d.image_count}张图片</div>`;
    }
    html += `<div class="match">对比: <b>${escapeHtml(d.best_match)}</b></div>`;
    if (!labeled) {
      html += `<div class="btn-group">`;
      html += `<button class="btn btn-correct" onclick="label(${i}, 'correct')">✓ 正确(闲聊)</button>`;
      html += `<button class="btn btn-sell" onclick="label(${i}, 'sell')">→ 出售</button>`;
      html += `<button class="btn btn-buy" onclick="label(${i}, 'buy')">→ 求购</button>`;
      html += `<button class="btn btn-chat" onclick="label(${i}, 'chat')">→ 闲聊</button>`;
      html += `<button class="btn btn-invalid" onclick="label(${i}, 'invalid')">🗑 无效</button>`;
      html += `</div>`;
    }
    html += `</div>`;
  }
  list.innerHTML = html;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function label(idx, label) {
  const d = allData.filter(d => {
    if (currentFilter === 'unlabeled') return !labels[d.text];
    if (currentFilter === 'labeled') return labels[d.text];
    if (currentFilter === 'has_image') return d.has_image;
    return true;
  })[idx];
  if (!d) return;
  
  const resp = await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'text=' + encodeURIComponent(d.text) + '&label=' + label + '&suspected=' + d.suspected_cat,
  });
  
  if (resp.ok) {
    labels[d.text] = {text: d.text, label: label, suspected_cat: d.suspected_cat};
    render();
  }
}

loadData();
</script>
</body>
</html>"""


class LabelHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/data":
            suspicious = load_suspicious()
            labels = load_labels()
            data = {"suspicious": suspicious, "labels": labels}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)
    
    def do_POST(self):
        if self.path == "/api/label":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            params = urllib.parse.parse_qs(body)
            text = params.get("text", [""])[0]
            label = params.get("label", [""])[0]
            suspected = params.get("suspected", [""])[0]
            
            if text and label:
                save_label(text, label, "chat", suspected)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            else:
                self.send_error(400)
        else:
            self.send_error(404)
    
    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    suspicious = load_suspicious()
    labels = load_labels()
    print(f"标注服务启动中...")
    print(f"  可疑消息: {len(suspicious)} 条")
    print(f"  已标注: {len(labels)} 条")
    print(f"  地址: http://localhost:{PORT}")
    print(f"\n在浏览器打开 http://localhost:{PORT} 开始标注")
    print(f"标注完成后按 Ctrl+C 退出\n")
    
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), LabelHandler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n标注服务已停止")
        labels = load_labels()
        print(f"共标注: {len(labels)} 条")
        print(f"已保存到: {LABELS_FILE}")
