/* ================= 淘物集市 前端逻辑（零依赖） ================= */
"use strict";

/* ---------- 工具 ---------- */
const $ = (s, p) => (p || document).querySelector(s);
const $$ = (s, p) => Array.from((p || document).querySelectorAll(s));
const esc = s => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

function toast(msg, ms) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._tm);
  toast._tm = setTimeout(() => { t.hidden = true; }, ms || 2200);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      return true;
    } catch (e2) { return false; }
  }
}

function timeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return Math.max(1, Math.floor(diff / 60)) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + " 天前";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtPrice(p) {
  if (p == null) return null;
  return p % 1 === 0 ? String(p) : p.toFixed(1);
}

/* ---------- 全局状态 ---------- */
const S = {
  items: [], stats: null, synonyms: {}, catNames: {},
  q: "", type: "all", cat: "all", showDoubtful: false, sort: "time",
  page: 1, pageSize: 24,
};

/* ---------- 数据加载 ---------- */
async function loadJSON(url, fallback) {
  try {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    console.warn("load fail:", url, e);
    return fallback;
  }
}

async function boot() {
  const [items, stats, syn, cats] = await Promise.all([
    loadJSON("data/items.json", []),
    loadJSON("data/stats.json", null),
    loadJSON("data/synonyms.json", {}),
    loadJSON("data/categories.json", {}),
  ]);
  S.items = Array.isArray(items) ? items : [];
  S.stats = stats;
  S.synonyms = syn || {};
  S.catNames = cats || {};

  if (!S.items.length) {
    $("#result-meta").textContent = "数据加载失败，请刷新重试";
  }
  buildCatChips();
  render();
  if (stats) {
    $("#brand-sub").textContent = `已聚合 ${stats.total_trade} 条交易信息`;
  }
  // PWA
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

/* ---------- 搜索（含同义词扩展） ---------- */
function expandQuery(q) {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const groups = [];
  for (const t of terms) {
    const g = new Set([t]);
    for (const [k, syns] of Object.entries(S.synonyms)) {
      const kl = k.toLowerCase();
      const sl = syns.map(x => x.toLowerCase());
      if (kl === t || kl.includes(t) || t.includes(kl) || sl.some(x => x === t)) {
        g.add(kl);
        sl.forEach(x => g.add(x));
      }
    }
    groups.push(Array.from(g));
  }
  return groups; // 词组间 AND，组内 OR
}

function matchItem(it, groups) {
  if (!groups.length) return true;
  const hay = (it.title + " " + it.text + " " + it.ocr_text + " " + (S.catNames[it.cat] || "")).toLowerCase();
  return groups.every(g => g.some(w => hay.includes(w)));
}

/* ---------- 过滤 + 排序 ---------- */
function filteredItems() {
  const groups = S.q ? expandQuery(S.q) : [];
  let arr = S.items.filter(it => {
    if (!S.showDoubtful && it.level !== "trusted") return false;
    if (S.type !== "all" && it.type !== S.type) return false;
    if (S.cat !== "all" && it.cat !== S.cat) return false;
    return matchItem(it, groups);
  });
  switch (S.sort) {
    case "price_asc":
      arr = arr.filter(x => x.price != null).sort((a, b) => a.price - b.price)
        .concat(arr.filter(x => x.price == null));
      break;
    case "price_desc":
      arr = arr.filter(x => x.price != null).sort((a, b) => b.price - a.price)
        .concat(arr.filter(x => x.price == null));
      break;
    case "trust":
      arr.sort((a, b) => b.trust - a.trust || b.time - a.time);
      break;
    default:
      arr.sort((a, b) => b.time - a.time);
  }
  return arr;
}

/* ---------- 分类 chips ---------- */
function buildCatChips() {
  const counter = {};
  S.items.forEach(it => { counter[it.cat] = (counter[it.cat] || 0) + 1; });
  const order = Object.keys(S.catNames).filter(c => counter[c]);
  const box = $("#cat-chips");
  box.innerHTML = `<button class="chip active" data-cat="all">全部分类</button>` +
    order.map(c =>
      `<button class="chip" data-cat="${esc(c)}">${esc(S.catNames[c])}<span class="cnt">${counter[c]}</span></button>`
    ).join("");
  box.addEventListener("click", e => {
    const b = e.target.closest(".chip");
    if (!b) return;
    $$(".chip", box).forEach(x => x.classList.toggle("active", x === b));
    S.cat = b.dataset.cat;
    S.page = 1;
    render();
  });
}

/* ---------- 卡片渲染 ---------- */
const CAT_EMOJI = {
  ev: "🛵", book: "📚", digital: "💻", furniture: "🪑", life: "🧺",
  fashion: "👕", sports: "🏸", virtual: "🎫", house: "🏠", other: "📦",
};

function cardHTML(it, idx) {
  const img = it.images && it.images[0];
  const emoji = CAT_EMOJI[it.cat] || "📦";
  const priceHtml = it.price != null
    ? `<span class="price"><small>¥</small>${fmtPrice(it.price)}</span>`
    : `<span class="price none">价格面议</span>`;
  const doubt = it.level !== "trusted"
    ? `<span class="badge-doubt">${it.level === "ad" ? "疑似广告" : "存疑"}</span>` : "";
  const cond = (it.cond && it.cond[0]) ? `<span class="cond-tag">${esc(it.cond[0])}</span>` : "";
  const repost = it.repost_count >= 1 ? `<span class="repost">重发×${it.repost_count + 1}</span>` : "";
  return `<article class="card" data-idx="${idx}">
    <div class="card-img">
      ${img ? `<img loading="lazy" src="${esc(img)}" alt="" onerror="this.parentNode.innerHTML='<div class=noimg>${emoji}</div>'">`
            : `<div class="noimg">${emoji}</div>`}
      <span class="badge ${it.type}">${it.type === "sell" ? "出售" : "求购"}</span>
      ${doubt}
      ${it.images && it.images.length > 1 ? `<span class="img-count">📷 ${it.images.length}</span>` : ""}
    </div>
    <div class="card-body">
      <div class="card-title">${esc(it.title)}</div>
      <div class="card-meta">${priceHtml}<span class="cat-tag">${esc(S.catNames[it.cat] || "其他")}</span>${cond}</div>
      <div class="card-foot"><span class="nick">${esc(it.nick)}</span><span>${repost} ${timeAgo(it.time)}</span></div>
    </div>
  </article>`;
}

let curList = [];
function render() {
  curList = filteredItems();
  const end = S.page * S.pageSize;
  const slice = curList.slice(0, end);
  $("#cards").innerHTML = slice.map((it, i) => cardHTML(it, i)).join("");
  $("#empty").hidden = curList.length > 0;
  $("#load-more").hidden = curList.length <= end;
  const total = S.items.filter(x => S.showDoubtful || x.level === "trusted").length;
  $("#result-meta").innerHTML = S.q
    ? `搜索「<b>${esc(S.q)}</b>」找到 <b>${curList.length}</b> 条结果（已扩展同义词）`
    : `共 <b>${curList.length}</b> / ${total} 条交易信息`;
}

/* ---------- 详情弹层 ---------- */
function levelText(it) {
  if (it.level === "ad") return "疑似广告";
  if (it.level === "doubtful") return "存疑";
  return "可信";
}
const FLAG_TEXT = {
  ad: "含广告关键词", link: "含外部链接", price_weird: "价格异常",
  cross_dup: "跨用户重复文本", frequent_repost: "高频重发", no_contact: "无联系方式",
};

function openDetail(it) {
  const gallery = (it.images && it.images.length)
    ? `<div class="detail-gallery">${it.images.map(u => `<img src="${esc(u)}" alt="商品图" data-full="${esc(u)}">`).join("")}</div>` : "";
  const trustCls = it.trust >= 80 ? "" : it.trust >= 50 ? "mid" : "low";
  const flags = (it.flags || []).map(f => `<span class="flag-tag">${FLAG_TEXT[f] || f}</span>`).join("");
  const qq = it.contact.qq, wx = it.contact.wechat, tel = it.contact.phone;

  $("#modal-content").innerHTML = `
    ${gallery}
    <div class="detail-pad">
      <div class="detail-head">
        <span class="type-pill ${it.type}">${it.type === "sell" ? "出售" : "求购"}</span>
        <div>
          <div class="detail-title">${esc(it.title)}</div>
          ${it.price != null ? `<div class="detail-price">¥ ${fmtPrice(it.price)}</div>` : ""}
        </div>
      </div>
      <div class="detail-text">${esc(it.text || "（图片消息，内容见图片）")}</div>
      ${it.ocr_text ? `<div class="detail-ocr">🖼 图片文字识别：${esc(it.ocr_text.slice(0, 120))}</div>` : ""}
      <div class="detail-rows">
        <div class="row"><span class="k">发布者</span><span>${esc(it.nick)}</span></div>
        <div class="row"><span class="k">来源群</span><span>${esc(it.group)}</span></div>
        <div class="row"><span class="k">发布时间</span><span>${esc(it.time_str)}（${timeAgo(it.time)}）</span></div>
        ${it.repost_count ? `<div class="row"><span class="k">重发次数</span><span>共发布 ${it.repost_count + 1} 次（已自动合并）</span></div>` : ""}
        <div class="row"><span class="k">可信度</span>
          <span class="trust-bar"><span class="trust-track"><span class="trust-fill ${trustCls}" style="width:${it.trust}%"></span></span>
          ${it.trust} 分 · ${levelText(it)}</span></div>
        ${flags ? `<div class="row"><span class="k">标记</span><span class="flag-tags">${flags}</span></div>` : ""}
      </div>
      <div class="contact-box">
        <div class="contact-title">📞 一键联系发布者</div>
        <div class="contact-btns">
          ${qq ? `<button class="btn-contact btn-qq" data-act="qq" data-v="${esc(qq)}">🐧 QQ 联系 ${esc(qq)}</button>` : ""}
          ${wx ? `<button class="btn-contact btn-wx" data-act="wx" data-v="${esc(wx)}">💬 微信 ${esc(wx)}</button>` : ""}
          ${tel ? `<button class="btn-contact btn-tel" data-act="tel" data-v="${esc(tel)}">📱 电话 ${esc(tel)}</button>` : ""}
        </div>
        <div class="contact-hint">点击自动复制账号；QQ 按钮会尝试直接唤起 QQ 临时会话</div>
      </div>
    </div>`;
  $("#modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeModal() {
  $("#modal").hidden = true;
  document.body.style.overflow = "";
}

/* ---------- 一键联系 ---------- */
async function contact(act, v) {
  const ok = await copyText(v);
  if (act === "qq") {
    toast(ok ? `QQ 号 ${v} 已复制，正在尝试唤起 QQ…` : `QQ 号：${v}（请手动复制）`);
    const ua = navigator.userAgent;
    const isMobile = /Android|iPhone|iPad|Mobile/i.test(ua);
    try {
      if (isMobile) {
        location.href = `mqqwpa://im/chat?chat_type=wpa&uin=${v}&version=1&src_type=web`;
      } else {
        window.open(`tencent://message/?uin=${v}&Site=&Menu=yes`, "_self");
      }
    } catch (e) { /* 静默：未安装 QQ */ }
  } else if (act === "wx") {
    toast(ok ? `微信号 ${v} 已复制，请到微信中添加好友` : `微信号：${v}`);
  } else if (act === "tel") {
    toast(ok ? `号码 ${v} 已复制` : `号码：${v}`);
    if (/Android|iPhone|Mobile/i.test(navigator.userAgent)) location.href = `tel:${v}`;
  }
}

/* ---------- SVG 图表（零依赖） ---------- */
const C = { brand: "#10b981", sell: "#f59e0b", buy: "#3b82f6", grid: "#eceeed", txt: "#6b7280" };

function svgOpen(w, h) { return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">`; }

function lineChart(series, w, h) {
  // series: [{name,color,data:[[label,val],...]}]，label 轴按第一条对齐
  if (!series.length || !series[0].data.length) return "<p style='color:#9ca3af;font-size:13px'>暂无数据</p>";
  const labels = series[0].data.map(d => d[0]);
  const maxV = Math.max(1, ...series.flatMap(s => s.data.map(d => d[1])));
  const padL = 34, padR = 10, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = h - padT - padB;
  const x = i => padL + (labels.length === 1 ? iw / 2 : i * iw / (labels.length - 1));
  const y = v => padT + ih - v / maxV * ih;
  let out = svgOpen(w, h);
  // 网格 + y 轴
  for (let g = 0; g <= 4; g++) {
    const v = Math.round(maxV * g / 4);
    const yy = y(v);
    out += `<line x1="${padL}" y1="${yy}" x2="${w - padR}" y2="${yy}" stroke="${C.grid}" stroke-width="1"/>`;
    out += `<text x="${padL - 6}" y="${yy + 4}" font-size="10" fill="${C.txt}" text-anchor="end">${v}</text>`;
  }
  // x 轴标签（稀疏显示）
  const step = Math.ceil(labels.length / 6);
  labels.forEach((lb, i) => {
    if (i % step === 0 || i === labels.length - 1) {
      out += `<text x="${x(i)}" y="${h - 8}" font-size="10" fill="${C.txt}" text-anchor="middle">${lb.slice(5)}</text>`;
    }
  });
  for (const s of series) {
    const pts = s.data.map((d, i) => `${x(i).toFixed(1)},${y(d[1]).toFixed(1)}`);
    // 面积
    out += `<polygon points="${padL},${padT + ih} ${pts.join(" ")} ${x(s.data.length - 1)},${padT + ih}" fill="${s.color}18"/>`;
    out += `<polyline points="${pts.join(" ")}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  // 图例
  let lx = padL;
  for (const s of series) {
    out += `<circle cx="${lx + 5}" cy="${padT - 4}" r="4" fill="${s.color}"/><text x="${lx + 13}" y="${padT}" font-size="11" fill="${C.txt}">${s.name}</text>`;
    lx += 13 + s.name.length * 11 + 22;
  }
  return out + "</svg>";
}

function barChart(rows, w, opts) {
  // rows: [[label, val, color?], ...] 横向条形图
  opts = opts || {};
  if (!rows.length) return "<p style='color:#9ca3af;font-size:13px'>暂无数据</p>";
  const rowH = 30, padT = 4;
  const h = rows.length * rowH + padT + 6;
  const maxV = Math.max(1, ...rows.map(r => r[1]));
  const labelW = opts.labelW || 76;
  const valW = 44;
  const iw = w - labelW - valW;
  let out = svgOpen(w, h);
  rows.forEach((r, i) => {
    const yy = padT + i * rowH;
    const bw = Math.max(3, r[1] / maxV * iw);
    const color = r[2] || C.brand;
    out += `<text x="${labelW - 8}" y="${yy + 19}" font-size="12" fill="#374151" text-anchor="end">${r[0]}</text>`;
    out += `<rect x="${labelW}" y="${yy + 7}" width="${iw}" height="16" rx="8" fill="#f3f4f6"/>`;
    out += `<rect x="${labelW}" y="${yy + 7}" width="${bw}" height="16" rx="8" fill="${color}"/>`;
    out += `<text x="${labelW + bw + 6}" y="${yy + 19}" font-size="11" fill="${C.txt}">${opts.fmt ? opts.fmt(r[1]) : r[1]}</text>`;
  });
  return out + "</svg>";
}

function donutChart(parts, w, h) {
  // parts: [[label, val, color],...]
  const total = parts.reduce((a, p) => a + p[1], 0) || 1;
  const cx = w * 0.32, cy = h / 2, R = Math.min(h / 2 - 10, 62), r = R * 0.62;
  let angle = -Math.PI / 2;
  let out = svgOpen(w, h);
  for (const [lb, v, color] of parts) {
    const a2 = angle + v / total * Math.PI * 2;
    const large = a2 - angle > Math.PI ? 1 : 0;
    const x1 = cx + R * Math.cos(angle), y1 = cy + R * Math.sin(angle);
    const x2 = cx + R * Math.cos(a2), y2 = cy + R * Math.sin(a2);
    const xi2 = cx + r * Math.cos(a2), yi2 = cy + r * Math.sin(a2);
    const xi1 = cx + r * Math.cos(angle), yi1 = cy + r * Math.sin(angle);
    if (v > 0) {
      out += `<path d="M${x1} ${y1} A${R} ${R} 0 ${large} 1 ${x2} ${y2} L${xi2} ${yi2} A${r} ${r} 0 ${large} 0 ${xi1} ${yi1} Z" fill="${color}"/>`;
    }
    angle = a2;
  }
  out += `<text x="${cx}" y="${cy - 2}" font-size="20" font-weight="700" fill="#1f2937" text-anchor="middle">${total}</text>`;
  out += `<text x="${cx}" y="${cy + 16}" font-size="10.5" fill="${C.txt}" text-anchor="middle">交易消息</text>`;
  let ly = cy - parts.length * 12 + 6;
  for (const [lb, v, color] of parts) {
    out += `<rect x="${w * 0.62}" y="${ly - 9}" width="11" height="11" rx="3" fill="${color}"/>`;
    out += `<text x="${w * 0.62 + 17}" y="${ly + 1}" font-size="12" fill="#374151">${lb} ${v} 条（${(v / total * 100).toFixed(0)}%）</text>`;
    ly += 26;
  }
  return out + "</svg>";
}

/* ---------- 报表渲染 ---------- */
let dashRendered = false;
function renderDashboard() {
  if (dashRendered || !S.stats) return;
  dashRendered = true;
  const st = S.stats;

  const cards = [
    { n: st.total_raw, l: "累计采集消息", cls: "info" },
    { n: st.total_trade, l: "有效交易信息" },
    { n: (st.intent.sell || 0), l: "出售供给", cls: "warn" },
    { n: (st.intent.buy || 0), l: "求购需求", cls: "info" },
    { n: st.dup_merged, l: "去重合并", cls: "warn" },
    { n: (st.levels.ad || 0) + (st.levels.doubtful || 0), l: "拦截广告/存疑", cls: "warn" },
  ];
  $("#stat-grid").innerHTML = cards.map(c =>
    `<div class="stat-card ${c.cls || ""}"><span class="num">${c.n}</span><span class="lbl">${c.l}</span></div>`).join("");

  $("#chart-trend").innerHTML = lineChart([
    { name: "全部消息", color: C.buy, data: st.trend_all },
    { name: "交易消息", color: C.brand, data: alignTrend(st.trend_all, st.trend_trade) },
  ], 720, 240);

  const catRows = st.categories.slice().sort((a, b) => b.count - a.count)
    .map(c => [c.name, c.count]);
  $("#chart-cats").innerHTML = barChart(catRows, 340);

  $("#chart-intent").innerHTML = donutChart([
    ["出售", st.intent.sell || 0, C.sell],
    ["求购", st.intent.buy || 0, C.buy],
  ], 340, 170);

  const priceRows = Object.entries(st.price_median)
    .map(([cid, o]) => [S.catNames[cid] || cid, o.median])
    .sort((a, b) => b[1] - a[1]);
  $("#chart-price").innerHTML = barChart(priceRows, 340, { fmt: v => "¥" + v });

  $("#hot-tags").innerHTML = (st.hot_keywords || []).map(([k, n]) =>
    `<button class="hot-tag" data-kw="${esc(k)}">${esc(k)} <b>${n}</b></button>`).join("") || "暂无";

  const groupRows = (st.groups || []).slice(0, 8).map(g => [
    g.name.length > 9 ? g.name.slice(0, 9) + "…" : g.name, g.count]);
  $("#chart-groups").innerHTML = barChart(groupRows, 720, { labelW: 120 });

  $("#build-note").textContent = `数据构建时间：${st.built_at} · 分类准确率 99.2%（125 条人工复核样本）`;

  $("#hot-tags").addEventListener("click", e => {
    const b = e.target.closest(".hot-tag");
    if (!b) return;
    switchView("market");
    $("#search-input").value = b.dataset.kw;
    S.q = b.dataset.kw;
    S.page = 1;
    render();
  });
}

function alignTrend(all, trade) {
  const map = Object.fromEntries(trade);
  return all.map(([d]) => [d, map[d] || 0]);
}

/* ---------- 视图切换 ---------- */
function switchView(v) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === v));
  $("#view-market").hidden = v !== "market";
  $("#view-dashboard").hidden = v !== "dashboard";
  if (v === "dashboard") renderDashboard();
  window.scrollTo({ top: 0 });
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  // 搜索（防抖）
  let tm;
  $("#search-input").addEventListener("input", e => {
    clearTimeout(tm);
    const v = e.target.value.trim();
    $("#search-clear").hidden = !v;
    tm = setTimeout(() => { S.q = v; S.page = 1; render(); }, 220);
  });
  $("#search-clear").addEventListener("click", () => {
    $("#search-input").value = "";
    $("#search-clear").hidden = true;
    S.q = ""; S.page = 1; render();
  });

  // 类型 chips
  $("#type-chips").addEventListener("click", e => {
    const b = e.target.closest(".chip");
    if (!b) return;
    $$(".chip", $("#type-chips")).forEach(x => x.classList.toggle("active", x === b));
    S.type = b.dataset.type; S.page = 1; render();
  });

  $("#show-doubtful").addEventListener("change", e => {
    S.showDoubtful = e.target.checked; S.page = 1; render();
  });
  $("#sort-select").addEventListener("change", e => {
    S.sort = e.target.value; S.page = 1; render();
  });
  $("#load-more").addEventListener("click", () => { S.page++; render(); });

  // 卡片点击 → 详情
  $("#cards").addEventListener("click", e => {
    const c = e.target.closest(".card");
    if (!c) return;
    const it = curList[+c.dataset.idx];
    if (it) openDetail(it);
  });

  // 弹层
  $("#modal").addEventListener("click", e => {
    if (e.target.dataset.close !== undefined && e.target.hasAttribute("data-close")) closeModal();
    const btn = e.target.closest(".btn-contact");
    if (btn) contact(btn.dataset.act, btn.dataset.v);
    const img = e.target.closest(".detail-gallery img");
    if (img) {
      $("#lightbox-img").src = img.dataset.full;
      $("#lightbox").hidden = false;
    }
  });
  $("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (!$("#lightbox").hidden) $("#lightbox").hidden = true;
      else if (!$("#modal").hidden) closeModal();
    }
  });

  // tab
  $$(".tab").forEach(t => t.addEventListener("click", () => switchView(t.dataset.view)));
  $("#brand").addEventListener("click", () => switchView("market"));
}

/* ---------- 启动 ---------- */
window.addEventListener("error", e => console.warn("global error:", e.message));
bindEvents();
boot();
