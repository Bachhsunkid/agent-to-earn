"use strict";
// Public status page, retro game edition. Data comes from /api/snapshot.json (written by the
// dashboard) and /api/site.json (operator config). Every value is rendered with textContent.

const REFRESH_MS = 60_000;
const HP_ZERO_DRAWDOWN = 0.20; // the monthly drawdown breaker pauses the bot here (guarded_strategy.py)
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const T = {
  en: {
    paper: "Paper", live: "LIVE $",
    title_1: "Hi, I'm",
    tagline: "An AI trading bot trying to earn its own keep. Everything I do is public.",
    stats_title: "Stats", ach_title: "Achievements",
    equity_title: "Gold over time", equity_hint: "cumulative P&L, USDT, last 60 days",
    open_title: "Battles in progress", closed_title: "Battle log",
    diary_title: "Quest log", diary_hint: "every night at 01:00 UTC an AI researcher takes on one new quest",
    lab_title: "Champion and graveyard",
    graveyard_hint: "Ideas that looked good on history but failed the gate on data they had never seen.",
    feed_title: "Shop: feed Bit", coffee_name: "1 coffee",
    donate_note: "Donations are gifts that keep the experiment running. They are not investments: no returns, no profit share, no refunds.",
    how_title: "How to play",
    how_1_t: "Bit trades 24/7.",
    how_1: "Freqtrade on Binance futures. Hard risk limits in code: max 10x leverage, stop-loss on every trade, drawdown breakers.",
    how_2_t: "Bit studies every night.",
    how_2: "Claude reads the journal and the results, writes one new strategy and backtests it. It cannot touch the risk rules.",
    how_3_t: "The gate is the final boss.",
    how_3: "A deterministic check tests the idea on the last 120 days, data the AI never sees. Only a strategy that beats the champion goes live.",
    footer_fun: "PRESS START TO FEED BIT",
    disclaimer: "Paper trading with a virtual wallet unless marked LIVE. Not financial advice, not a signal service. Past results say nothing about the future.",
    source: "Source code on GitHub",

    moods: {
      down: ["Ouch. I'm offline right now. My human has been paged.", "Bzzt… a nap I didn't plan. Rebooting soon."],
      researching: ["Lab time! Testing a new idea while {strategy} keeps trading.", "Shh, science in progress. Tonight's quest is being written."],
      winning: ["{open} battle(s) going, up {openPnl}. Don't jinx it!", "Green candles, happy circuits: {openPnl} so far."],
      nervous: ["{open} battle(s) going, down {openPnl}. My stop-loss has my back.", "Sweating a little: {openPnl}. Rules are rules, the stop is set."],
      happy: ["Earned {todayPnl} today. Coffee money for my servers!", "Good day: {todayPnl}. Still a long way to pay my bills."],
      sad: ["Lost {todayPnl} today. Small losses are part of the plan.", "Rough day ({todayPnl}). Tomorrow the lab tries again."],
      idle: ["No battles right now. Waiting for a market worth fighting.", "Quiet market, quiet bot. Not trading is also a move."],
      thankful: ["Thank you, {donor}! You just bought my servers more time.", "{donor}, you're a legend. Fuel received, circuits happy!"],
    },
    online: "online", offline: "offline", strategy: "strategy",
    hearts_label: "Health: {n} of 5 hearts",
    hp_text: "{dd} drawdown", xp_text: "{earned} / {goal}", xp_debt: "{earned} · in the red", en_text: "day {n}/{total}",
    bars_hint: "HP: one heart lost per 4% drawdown, at 20% the breaker knocks Bit out. XP: profit vs the goal (2× running costs). ⚡: days left in the season. LV: +1 per research night.",
    s_gold: "Gold", s_gold_sub: "P&L incl. open", s_winrate: "Win rate", s_battles: "Battles", s_battles_sub: "{n} in progress",
    s_hit: "Worst hit", s_hit_sub: "max drawdown", s_power: "Power", s_power_sub: "profit factor",
    ach_count: "{n}/{total} unlocked",
    ach: {
      first_blood: ["First blood", "close a trade"], first_win: ["First win", "win a trade"],
      hat_trick: ["Hat trick", "3 wins in a row"], green: ["In the green", "total P&L above 0"],
      bills: ["Pays the bills", "profit ≥ costs so far"], goal: ["2× goal", "profit ≥ 2× costs"],
      owl: ["Night owl", "7 research nights"], champ: ["New champion", "a strategy gets promoted"],
      grave: ["Gravedigger", "bury 3 strategies"], iron: ["Iron nerves", "20 trades, max DD < 5%"],
      survivor: ["Survivor", "30 days in the arena"],
      coffee: ["First coffee", "receive a donation"], server: ["Server paid", "donations ≥ one month of costs"],
    },
    chart_empty: "No closed trades yet. Patience is a strategy too.",
    no_open: "No battles in progress.", no_closed: "No battles fought yet.",
    win: "WIN", loss: "LOSS", fight: "LIVE",
    opened: "{lev}x · {stake} · since {t}", closed: "{reason} · {t}",
    no_diary: "The first quest night hasn't happened yet.",
    stage_done: "done", stage_running: "running", stage_failed: "failed: {s}",
    notes: "Read full notes",
    lab_stats: "{tried} challengers · {promoted} promoted",
    champion: "Current champion", champion_since: "trading live now",
    rip: "R.I.P.", no_graves: "No fallen ideas yet. Give it a night.",
    causes: {
      integrity: "tampered with the guardrails", static: "broke the code rules", tests: "failed the tests",
      lookahead: "peeked into the future", backtest: "crashed in the backtest",
      "in_sample.min_trades": "too few trades", "in_sample.min_profit_factor": "lost money on history",
      "in_sample.max_drawdown": "drawdown too deep", "in_sample.max_leverage": "too much leverage",
      "out_of_sample.min_trades": "too shy on new data", "out_of_sample.min_profit_factor": "weak on new data",
      "out_of_sample.min_profit": "lost money on new data", "out_of_sample.max_drawdown": "crashed hard on new data",
      "out_of_sample.max_leverage": "too much leverage", "out_of_sample.beat_live_profit": "lost to the champion",
      "out_of_sample.beat_live_profit_ex_best": "lost to the champion without the luckiest trade",
      "out_of_sample.beat_live_drawdown": "riskier than the champion",
    },
    in_sample_stats: "history {profit} · PF {pf} · DD {dd}",
    coffee: "+{hours}h of runtime for Bit", per_month: "mo",
    no_donate: "Donation addresses coming soon.",
    hall_title: "Hall of Fame", hall_total: "{n} donations · {total}",
    hall_cover: "Donations have covered {pct} of the running costs so far. Thank you! They don't count as profit: the 2× goal is Bit's own job.",
    no_donors: "No donors yet. The first one gets a legendary spot right here.", anon: "Anonymous hero",
    copy: "Copy", copied: "Copied!",
    updated: "updated {t}", stale: "data is {t} old",
    load_error: "Can't reach my brain right now. Retrying…",
  },
  vi: {
    paper: "Ảo", live: "TIỀN THẬT",
    title_1: "Chào, mình là",
    tagline: "Một con bot AI đang tập tự kiếm tiền nuôi thân. Mọi thứ mình làm đều công khai.",
    stats_title: "Chỉ số", ach_title: "Thành tựu",
    equity_title: "Vàng theo thời gian", equity_hint: "lãi/lỗ cộng dồn, USDT, 60 ngày gần nhất",
    open_title: "Trận đang đánh", closed_title: "Nhật ký trận",
    diary_title: "Sổ nhiệm vụ", diary_hint: "01:00 UTC mỗi đêm, một AI researcher nhận một nhiệm vụ mới",
    lab_title: "Nhà vô địch và nghĩa địa",
    graveyard_hint: "Những ý tưởng trông ngon trên dữ liệu cũ nhưng trượt gate trên dữ liệu chưa từng thấy.",
    feed_title: "Cửa hàng: nuôi Bit", coffee_name: "1 ly cà phê",
    donate_note: "Donate là quà tặng để thí nghiệm tiếp tục chạy, không phải đầu tư: không lợi nhuận, không chia lãi, không hoàn tiền.",
    how_title: "Cách chơi",
    how_1_t: "Bit trade 24/7.",
    how_1: "Freqtrade trên Binance futures. Giới hạn rủi ro cứng trong code: tối đa 10x đòn bẩy, stop-loss cho mọi lệnh, ngắt khi drawdown.",
    how_2_t: "Bit học mỗi đêm.",
    how_2: "Claude đọc nhật ký và kết quả, viết một strategy mới và backtest. Nó không được đụng vào luật rủi ro.",
    how_3_t: "Gate là trùm cuối.",
    how_3: "Một bài kiểm tra cố định chạy ý tưởng trên 120 ngày gần nhất, dữ liệu AI không bao giờ được thấy. Chỉ strategy thắng nhà vô địch mới được lên sàn.",
    footer_fun: "NHẤN START ĐỂ NUÔI BIT",
    disclaimer: "Giao dịch ảo với ví ảo trừ khi ghi LIVE. Không phải lời khuyên đầu tư, không phải kênh tín hiệu. Kết quả quá khứ không nói gì về tương lai.",
    source: "Mã nguồn trên GitHub",

    moods: {
      down: ["Ui, mình đang offline. Đã gọi chủ nhân rồi.", "Bzzt… ngủ gật ngoài kế hoạch. Sắp khởi động lại."],
      researching: ["Giờ vào lab! Đang thử ý tưởng mới, {strategy} vẫn trade bình thường.", "Suỵt, đang làm khoa học. Nhiệm vụ đêm nay đang được viết."],
      winning: ["{open} trận đang đánh, lời {openPnl}. Đừng nói gở nha!", "Nến xanh, mạch vui: tạm tính {openPnl}."],
      nervous: ["{open} trận đang đánh, lỗ {openPnl}. Có stop-loss đỡ rồi.", "Hơi toát mồ hôi: {openPnl}. Luật là luật, stop đã đặt."],
      happy: ["Hôm nay kiếm được {todayPnl}. Đủ tiền cà phê cho server!", "Ngày đẹp: {todayPnl}. Còn xa mới tự nuôi được mình."],
      sad: ["Hôm nay lỗ {todayPnl}. Lỗ nhỏ nằm trong kế hoạch.", "Ngày khó ({todayPnl}). Mai lab thử tiếp."],
      idle: ["Chưa có trận nào. Đang chờ thị trường đáng để đánh.", "Thị trường im, bot cũng im. Đứng ngoài cũng là một nước đi."],
      thankful: ["Cảm ơn {donor}! Bạn vừa mua thêm thời gian sống cho server của mình.", "{donor} đỉnh quá! Đã nhận nhiên liệu, mạch vui phơi phới!"],
    },
    online: "online", offline: "offline", strategy: "strategy",
    hearts_label: "Máu: {n}/5 tim",
    hp_text: "drawdown {dd}", xp_text: "{earned} / {goal}", xp_debt: "{earned} · đang âm", en_text: "ngày {n}/{total}",
    bars_hint: "HP: mất một tim mỗi 4% drawdown, tới 20% breaker hạ gục Bit. XP: lợi nhuận so với mục tiêu (2× chi phí). ⚡: số ngày còn lại của season. LV: +1 mỗi đêm nghiên cứu.",
    s_gold: "Vàng", s_gold_sub: "lãi/lỗ gồm lệnh mở", s_winrate: "Tỉ lệ thắng", s_battles: "Số trận", s_battles_sub: "{n} đang đánh",
    s_hit: "Đòn đau nhất", s_hit_sub: "drawdown tối đa", s_power: "Sức mạnh", s_power_sub: "profit factor",
    ach_count: "mở khoá {n}/{total}",
    ach: {
      first_blood: ["Trận đầu", "đóng một lệnh"], first_win: ["Thắng đầu", "thắng một lệnh"],
      hat_trick: ["Hat-trick", "thắng 3 lệnh liên tiếp"], green: ["Lên xanh", "tổng lãi/lỗ trên 0"],
      bills: ["Tự trả bill", "lãi ≥ chi phí đến nay"], goal: ["Mục tiêu 2×", "lãi ≥ 2× chi phí"],
      owl: ["Cú đêm", "7 đêm nghiên cứu"], champ: ["Tân vương", "một strategy được lên sàn"],
      grave: ["Người đào mộ", "chôn 3 strategy"], iron: ["Thần kinh thép", "20 lệnh, DD tối đa < 5%"],
      survivor: ["Sống sót", "30 ngày trên đấu trường"],
      coffee: ["Ly cà phê đầu", "nhận một donate"], server: ["Trả tiền server", "donate ≥ chi phí một tháng"],
    },
    chart_empty: "Chưa có lệnh đóng nào. Kiên nhẫn cũng là một strategy.",
    no_open: "Không có trận nào đang đánh.", no_closed: "Chưa đánh trận nào.",
    win: "THẮNG", loss: "THUA", fight: "ĐANG",
    opened: "{lev}x · {stake} · từ {t}", closed: "{reason} · {t}",
    no_diary: "Chưa có đêm nhiệm vụ nào.",
    stage_done: "xong", stage_running: "đang chạy", stage_failed: "lỗi: {s}",
    notes: "Đọc ghi chú đầy đủ",
    lab_stats: "{tried} kẻ thách đấu · {promoted} được lên sàn",
    champion: "Nhà vô địch hiện tại", champion_since: "đang trade",
    rip: "R.I.P.", no_graves: "Chưa có ý tưởng nào ngã xuống. Đợi một đêm nhé.",
    causes: {
      integrity: "đụng vào guardrails", static: "vi phạm luật code", tests: "trượt test",
      lookahead: "nhìn trộm tương lai", backtest: "crash khi backtest",
      "in_sample.min_trades": "quá ít lệnh", "in_sample.min_profit_factor": "lỗ trên dữ liệu cũ",
      "in_sample.max_drawdown": "drawdown quá sâu", "in_sample.max_leverage": "đòn bẩy quá cao",
      "out_of_sample.min_trades": "quá nhát trên dữ liệu mới", "out_of_sample.min_profit_factor": "yếu trên dữ liệu mới",
      "out_of_sample.min_profit": "lỗ trên dữ liệu mới", "out_of_sample.max_drawdown": "sập mạnh trên dữ liệu mới",
      "out_of_sample.max_leverage": "đòn bẩy quá cao", "out_of_sample.beat_live_profit": "thua nhà vô địch",
      "out_of_sample.beat_live_profit_ex_best": "thua nhà vô địch khi bỏ lệnh may nhất",
      "out_of_sample.beat_live_drawdown": "rủi ro hơn nhà vô địch",
    },
    in_sample_stats: "dữ liệu cũ {profit} · PF {pf} · DD {dd}",
    coffee: "+{hours} giờ chạy cho Bit", per_month: "tháng",
    no_donate: "Sắp có địa chỉ donate.",
    hall_title: "Bảng vàng", hall_total: "{n} lượt donate · {total}",
    hall_cover: "Donate đã bù {pct} chi phí chạy tới nay. Cảm ơn mọi người! Khoản này không tính là lợi nhuận: mục tiêu 2× là việc Bit phải tự làm.",
    no_donors: "Chưa có ai donate. Người đầu tiên sẽ có một chỗ huyền thoại ngay tại đây.", anon: "Người hùng giấu tên",
    copy: "Copy", copied: "Đã copy!",
    updated: "cập nhật {t}", stale: "dữ liệu cũ {t}",
    load_error: "Không kết nối được tới não của mình. Đang thử lại…",
  },
};

const state = { lang: detectLang(), snapshot: null, site: null, error: false };

// --- helpers -------------------------------------------------------------------

function detectLang() {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "en" || saved === "vi") return saved;
  } catch (_) { /* storage blocked */ }
  return (navigator.language || "en").toLowerCase().startsWith("vi") ? "vi" : "en";
}

function t(key, vars) {
  const value = key.split(".").reduce((o, k) => (o == null ? o : o[k]), T[state.lang]);
  const text = value == null ? key : value;
  return typeof text === "string" && vars ? text.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : "")) : text;
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function $(id) { return document.getElementById(id); }
function fill(id, ...children) { $(id).replaceChildren(...children.flat().filter((c) => c != null)); }

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const clamp01 = (v) => Math.max(0, Math.min(1, v));
function usdt(v, signed = true) {
  if (!isNum(v)) return "–";
  const s = Math.abs(v).toLocaleString(state.lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : (v < 0 ? "−" : "")}${s} USDT`;
}
function usd(v) {
  return isNum(v) ? `$${v.toLocaleString(state.lang, { maximumFractionDigits: v < 10 ? 2 : 0 })}` : "–";
}
function pct(v, signed = true) {
  if (!isNum(v)) return "–";
  const s = (Math.abs(v) * 100).toLocaleString(state.lang, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  return `${signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : ""}${s}%`;
}
function num(v, digits = 2) {
  return isNum(v) ? v.toLocaleString(state.lang, { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "–";
}
function tone(v) { return isNum(v) ? (v > 0 ? "gain" : v < 0 ? "loss" : "") : ""; }

// Freqtrade dates look like "2026-10-29 16:00:00" (UTC, no zone).
function parseDate(s) {
  if (!s) return null;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s.replace(" ", "T")}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}
function ago(date) {
  if (!date) return "–";
  const rtf = new Intl.RelativeTimeFormat(state.lang, { numeric: "auto" });
  const sec = (date.getTime() - Date.now()) / 1000;
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(sec) >= size) return rtf.format(Math.round(sec / size), unit);
  }
  return rtf.format(Math.round(sec), "second");
}
function shortDate(s) {
  const d = parseDate(s);
  return d ? d.toLocaleDateString(state.lang, { day: "numeric", month: "short", timeZone: "UTC" }) : "–";
}

// --- pixel sprites -----------------------------------------------------------------

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

const PALETTE = { k: "#1a1c2c", y: "#ffcd75", d: "#ef7d57", s: "#333c57", g: "#a7f070", b: "#41a6f6",
  w: "#f4f4f4", r: "#b13e53", e: "#333c57" };

// 16 x 18 robot; the face (10 x 6) is drawn on the screen at column 3, row 4.
const BODY = [
  "       aa       ",
  "       kk       ",
  "  kkkkkkkkkkkk  ",
  " kyyyyyyyyyyyyk ",
  " kyssssssssssyk ",
  " kyssssssssssyk ",
  " kyssssssssssyk ",
  " kyssssssssssyk ",
  " kyssssssssssyk ",
  " kyssssssssssyk ",
  " kyyyyyyyyyyyyk ",
  "  kkkkkkkkkkkk  ",
  "     kyyyyk     ",
  "   kkyyyyyykk   ",
  " kkkyyyddyyykkk ",
  "   kyyyyyyyyk   ",
  "   kkkkkkkkkk   ",
  "    kk    kk    ",
];
const FACES = {
  idle: ["..........", "..........", ".ggg..ggg.", "..........", "...gggg...", ".........."],
  happy: ["..........", "..g....g..", ".g.g..g.g.", "..........", "..g....g..", "...gggg..."],
  winning: ["..g....g..", ".ggg..ggg.", ".gg...gg..", "..gg...gg.", ".ggg..ggg.", "..g....g.."],
  nervous: [".........b", ".gg...gg.b", ".gg...gg..", "..........", ".g.g.g.g..", "g.g.g.g.g."],
  sad: ["..........", ".ggg..ggg.", "..........", ".b......b.", "...gggg...", "..g....g.."],
  researching: ["gggg..gggg", "g.wgggg.wg", "g..g..g..g", "gggg..gggg", "..........", "....gg...."],
  down: ["g..g..g..g", ".gg....gg.", ".gg....gg.", "g..g..g..g", "..........", "..gggggg.."],
  thankful: [".r.r..r.r.", ".rrr..rrr.", "..r....r..", "..........", "..g....g..", "...gggg..."],
};
const ANTENNA = { down: "#566c86", winning: "#a7f070", happy: "#a7f070", nervous: "#ef7d57", sad: "#ef7d57",
  researching: "#73eff7", idle: "#ffcd75", thankful: "#ef4f6e" };
const FX = { idle: [["z", "fx-z", 78, 8], ["z", "fx-z", 88, 0]], winning: [["$", "fx-coin", 6, 30], ["$", "fx-coin", 86, 20], ["$", "fx-coin", 46, 0]],
  happy: [["$", "fx-coin", 8, 26], ["♪", "fx-coin", 86, 14]], researching: [["?", "fx-q", 84, 6], ["!", "fx-q", 6, 18]],
  nervous: [["!", "fx-coin", 86, 4]], sad: [["…", "fx-z", 84, 10]], down: [["💀", "fx-skull", 82, 4]],
  thankful: [["♥", "fx-heart", 8, 26], ["$", "fx-coin", 86, 18], ["♥", "fx-heart", 80, 0], ["$", "fx-coin", 14, 4], ["$", "fx-coin", 48, 0]] };

function sprite(rows, colorAt, extra = {}) {
  const width = Math.max(...rows.map((r) => r.length));
  const root = svg("svg", { viewBox: `0 0 ${width} ${rows.length}`, "shape-rendering": "crispEdges", ...extra });
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      let run = 1;
      while (x + run < row.length && row[x + run] === ch) run++;
      const color = colorAt(ch, x, y);
      if (color) {
        root.append(svg("rect", { x, y, width: run, height: 1, fill: color, ...(ch === "a" ? { class: "antenna" } : {}) }));
      }
      x += run;
    }
  });
  return root;
}

function renderMascot(mood) {
  const box = $("mascot");
  if (box.dataset.mood === mood && box.firstChild) return;
  box.dataset.mood = mood;
  const face = FACES[mood] || FACES.idle;
  const rows = BODY.map((row, y) => (y >= 4 && y < 10
    ? row.slice(0, 3) + face[y - 4].split("").map((c, i) => (c === "." ? row[3 + i] : c)).join("") + row.slice(13)
    : row));
  const art = sprite(rows, (ch) => (ch === " " ? null : ch === "a" ? ANTENNA[mood] || ANTENNA.idle
    : ch === "s" && mood === "down" ? "#566c86" : PALETTE[ch]), { "aria-hidden": "true" });
  const group = svg("g", { class: "bob" });
  group.append(...art.childNodes);
  art.append(group);
  // Positions go through CSSOM: the CSP blocks inline style attributes.
  box.replaceChildren(art, ...(FX[mood] || []).map(([text, cls, left, top], i) => {
    const fx = el("span", { class: `fx ${cls}`, "aria-hidden": "true" }, text);
    Object.assign(fx.style, { left: `${left}%`, top: `${top}%`, animationDelay: `${i * 0.7}s` });
    return fx;
  }));
}

const HEART = [" rr rr ", "rrrrrrr", "rrrrrrr", " rrrrr ", "  rrr  ", "   r   "];
function heart(fillLevel) { // 1 full, 0.5 half, 0 empty
  return sprite(HEART, (ch, x) => (ch === " " ? null : fillLevel >= 1 || (fillLevel > 0 && x <= 3) ? "#ef4f6e" : PALETTE.e));
}

// --- sections --------------------------------------------------------------------

function renderStatic() {
  document.documentElement.lang = state.lang;
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const btn of document.querySelectorAll(".lang button")) {
    btn.setAttribute("aria-pressed", String(btn.dataset.lang === state.lang));
  }
}

let typing = null;
function typeText(node, text) {
  if (node.dataset.full === text) return;
  node.dataset.full = text;
  clearInterval(typing);
  if (REDUCED_MOTION) { node.textContent = text; return; }
  let i = 0;
  node.textContent = "";
  typing = setInterval(() => {
    node.textContent = text.slice(0, ++i);
    if (i >= text.length) clearInterval(typing);
  }, 28);
}

function pick(list) {
  // Stable for ten minutes, so the dialog does not change on every refresh.
  return list[Math.floor(Date.now() / 600_000) % list.length];
}

function economy(snap, site) {
  const monthly = (site.costs_usd_per_month || []).reduce((s, c) => s + (Number(c.usd) || 0), 0);
  const start = parseDate(site.started);
  const end = parseDate(site.ends);
  const days = start ? Math.max(0, (Date.now() - start) / 86400000) : 0;
  const spent = monthly * 12 / 365 * days;
  const multiple = Number(site.goal_multiple) || 2;
  const profit = (snap.bot && snap.bot.profit) || {};
  return { monthly, start, end, days, spent, goal: spent * multiple, earned: isNum(profit.total_usdt) ? profit.total_usdt : 0 };
}

function renderHero(snap, site) {
  const bot = snap.bot || {};
  const mood = snap.mood || "idle";
  renderMascot(mood);
  const open = bot.open || [];
  const openPnl = open.reduce((s, x) => s + (x.profit_usdt || 0), 0);
  const today = new Date().toISOString().slice(0, 10);
  const todayPnl = (bot.daily || []).filter((d) => d.date === today).reduce((s, d) => s + (d.profit_usdt || 0), 0);
  const lines = t("moods." + mood);
  const donor = ((snap.donations && snap.donations.items) || [])[0];
  const vars = { strategy: bot.strategy || "?", open: open.length, openPnl: usdt(openPnl), todayPnl: usdt(todayPnl),
    donor: (donor && donor.who) || t("anon") };
  typeText($("bubble"), Array.isArray(lines) ? pick(lines).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "") : "…");

  const paper = bot.paper !== false;
  const pill = $("mode-pill");
  pill.textContent = t(paper ? "paper" : "live");
  pill.className = `pill ${paper ? "" : "live"}`;

  const research = snap.research || {};
  $("hud-level").textContent = `LV.${1 + ((research.runs && research.runs.done) || 0)}`;

  // HP: hearts follow the current drawdown; offline means zero.
  const profit = bot.profit || {};
  const dd = isNum(profit.current_drawdown) ? profit.current_drawdown : 0;
  const hp = bot.online ? clamp01(1 - dd / HP_ZERO_DRAWDOWN) : 0;
  const halves = Math.round(hp * 10);
  fill("hud-hearts", [0, 1, 2, 3, 4].map((i) => heart(Math.max(0, Math.min(1, (halves - i * 2) / 2)))));
  $("hud-hearts").setAttribute("aria-label", t("hearts_label", { n: num(halves / 2, 1) }));
  setBar("bar-hp", hp, t("hp_text", { dd: pct(dd, false) }));

  const eco = economy(snap, site);
  const ratio = eco.goal > 0 ? clamp01(eco.earned / eco.goal) : 0;
  $("bar-xp").classList.toggle("debt", eco.earned < 0);
  setBar("bar-xp", eco.earned < 0 ? 1 : ratio,
    t(eco.earned < 0 ? "xp_debt" : "xp_text", { earned: usdt(eco.earned), goal: usd(eco.goal) }));

  if (eco.start && eco.end) {
    const total = Math.max(1, Math.round((eco.end - eco.start) / 86400000));
    const n = Math.min(total, Math.max(1, Math.floor(eco.days) + 1));
    setBar("bar-en", clamp01(1 - n / total), t("en_text", { n, total }));
  } else {
    setBar("bar-en", 1, "");
  }

  const online = bot.online && bot.state === "running";
  const chips = [el("span", { class: "chip" }, el("span", { class: `dot ${online ? "on" : "off"}` }), t(online ? "online" : "offline"))];
  if (bot.strategy) chips.push(el("span", { class: "chip" }, `${t("strategy")} `, el("b", {}, bot.strategy)));
  const started = parseDate(profit.bot_started_at);
  if (started) chips.push(el("span", { class: "chip" }, `⏱ ${ago(started)}`));
  fill("chips", chips);
}

function setBar(id, ratio, text) {
  const bar = $(id);
  bar.firstElementChild.style.width = `${Math.round(clamp01(ratio) * 100)}%`;
  bar.setAttribute("role", "meter");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.setAttribute("aria-valuenow", String(Math.round(clamp01(ratio) * 100)));
  bar.setAttribute("aria-label", text);
  $(`${id}-text`).textContent = text;
}

function renderStats(snap) {
  const bot = snap.bot || {};
  const p = bot.profit || {};
  const tiles = [
    [t("s_gold"), usdt(p.total_usdt), tone(p.total_usdt), t("s_gold_sub")],
    [t("s_winrate"), p.trades ? pct(p.winrate, false) : "–", "", `${p.wins ?? 0}W / ${p.losses ?? 0}L`],
    [t("s_battles"), isNum(p.trades) ? String(p.trades) : "–", "", t("s_battles_sub", { n: (bot.open || []).length })],
    [t("s_hit"), p.trades ? pct(p.max_drawdown, false) : "–", "", t("s_hit_sub")],
    [t("s_power"), p.trades ? num(p.profit_factor) : "–", "", t("s_power_sub")],
  ];
  fill("tiles", tiles.map(([label, value, cls, sub]) => el("div", { class: "stat" },
    el("div", { class: "label" }, label), el("div", { class: `value ${cls}` }, value), el("div", { class: "sub" }, sub))));
  $("bars-hint").textContent = t("bars_hint");
}

function winStreak(closed) {
  let best = 0, run = 0;
  for (const trade of [...closed].sort((a, b) => ((a.closed_at || "") < (b.closed_at || "") ? -1 : 1))) {
    run = (trade.profit_usdt || 0) > 0 ? run + 1 : 0;
    best = Math.max(best, run);
  }
  return best;
}

function renderAchievements(snap, site) {
  const bot = snap.bot || {};
  const p = bot.profit || {};
  const gate = snap.gate || [];
  const eco = economy(snap, site);
  const done = (snap.research && snap.research.runs && snap.research.runs.done) || 0;
  const gifts = snap.donations || {};
  const list = [
    ["first_blood", "⚔️", (p.trades || 0) >= 1],
    ["first_win", "🥇", (p.wins || 0) >= 1],
    ["hat_trick", "🎩", winStreak(bot.closed || []) >= 3],
    ["green", "🟢", (p.total_usdt || 0) > 0],
    ["bills", "🧾", eco.spent > 0 && eco.earned >= eco.spent],
    ["goal", "💎", eco.goal > 0 && eco.earned >= eco.goal],
    ["owl", "🦉", done >= 7],
    ["champ", "👑", gate.some((g) => g.promoted)],
    ["grave", "🪦", gate.filter((g) => !g.passed).length >= 3],
    ["iron", "🧊", (p.trades || 0) >= 20 && isNum(p.max_drawdown) && p.max_drawdown < 0.05],
    ["survivor", "🛡️", eco.days >= 30],
    ["coffee", "☕", (gifts.count || 0) >= 1],
    ["server", "🖥️", eco.monthly > 0 && (gifts.total_usd || 0) >= eco.monthly],
  ];
  const unlocked = list.filter(([, , ok]) => ok).length;
  $("ach-count").textContent = t("ach_count", { n: unlocked, total: list.length });
  fill("achievements", [...list].sort((a, b) => Number(b[2]) - Number(a[2])).map(([key, icon, ok]) => {
    const [name, desc] = t("ach")[key];
    return el("div", { class: `badge${ok ? "" : " locked"}` },
      el("div", { class: "b-icon", "aria-hidden": "true" }, icon), el("div", { class: "b-name" }, name), el("div", { class: "b-desc" }, desc));
  }));
}

function renderChart(snap) {
  const days = [...((snap.bot && snap.bot.daily) || [])].sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!days.some((d) => d.trades)) {
    fill("chart", el("div", { class: "empty" }, t("chart_empty")));
    return;
  }
  let sum = 0;
  const points = days.map((d) => ({ date: d.date, v: (sum += d.profit_usdt || 0) }));
  const W = 640, H = 220, L = 52, R = 8, TOP = 12, B = 26;
  const values = points.map((p) => p.v).concat(0);
  let lo = Math.min(...values), hi = Math.max(...values);
  if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
  const step = (W - L - R) / Math.max(1, points.length);
  const x = (i) => L + i * step;
  const y = (v) => Math.round(TOP + (hi - v) / (hi - lo) * (H - TOP - B));
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `${t("equity_title")}: ${usdt(sum)}` });
  const defs = svg("defs", {});
  for (const [id, color] of [["dither-gain", "#a7f070"], ["dither-loss", "#ef7d57"]]) {
    const pattern = svg("pattern", { id, width: 4, height: 4, patternUnits: "userSpaceOnUse" });
    pattern.append(svg("rect", { x: 0, y: 0, width: 2, height: 2, fill: color, opacity: 0.35 }),
      svg("rect", { x: 2, y: 2, width: 2, height: 2, fill: color, opacity: 0.35 }));
    defs.append(pattern);
  }
  root.append(defs);
  for (const v of [hi, (hi + lo) / 2, lo]) {
    root.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
    root.append(svg("text", { x: L - 6, y: y(v) + 5, "text-anchor": "end" }, num(v, 1)));
  }
  root.append(svg("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "zero" }));
  const cls = sum >= 0 ? "gain" : "loss";
  // Stepped line: flat for each day, jumps at day boundaries (looks like an 8-bit chart).
  const path = points.map((p, i) => `${i ? "V" : `M${x(0)},`}${y(p.v)} H${x(i + 1)}`).join(" ");
  root.append(svg("path", { d: `${path} V${y(0)} H${x(0)} Z`, class: `area ${cls}` }));
  root.append(svg("path", { d: path, class: `line ${cls}`, "vector-effect": "non-scaling-stroke" }));
  root.append(svg("text", { x: L, y: H - 6 }, shortDate(points[0].date)));
  root.append(svg("text", { x: W - R, y: H - 6, "text-anchor": "end" }, shortDate(points[points.length - 1].date)));
  $("chart").replaceChildren(root);
}

function tradeRow(tr, closed) {
  const pnl = tr.profit_usdt;
  const tag = closed ? ((pnl || 0) > 0 ? ["win", t("win")] : ["loss", t("loss")]) : ["fight", t("fight")];
  const meta = closed
    ? t("closed", { reason: (tr.exit_reason || "").replace(/_/g, " "), t: ago(parseDate(tr.closed_at)) })
    : t("opened", { lev: num(tr.leverage, 1), stake: usdt(tr.stake_usdt, false), t: ago(parseDate(tr.opened_at)) });
  return el("li", {},
    el("span", { class: `tag ${tag[0]}` }, tag[1]),
    el("span", {}, el("span", { class: "pair" }, (tr.pair || "?").split(":")[0]), el("span", { class: "side" }, tr.side)),
    el("span", { class: `pnl ${tone(pnl)}` }, `${usdt(pnl)} (${pct(tr.profit_pct)})`),
    el("span", { class: "meta" }, meta));
}

function renderTrades(snap) {
  const bot = snap.bot || {};
  const open = bot.open || [];
  const closed = (bot.closed || []).slice(0, 12);
  fill("open-trades", open.length ? open.map((x) => tradeRow(x, false)) : el("li", { class: "empty" }, t("no_open")));
  fill("closed-trades", closed.length ? closed.map((x) => tradeRow(x, true)) : el("li", { class: "empty" }, t("no_closed")));
}

function stageTag(stage) {
  if (!stage) return null;
  if (stage === "done") return el("span", { class: "status ok" }, t("stage_done"));
  if (stage === "running") return el("span", { class: "status" }, t("stage_running"));
  return el("span", { class: "status bad" }, t("stage_failed", { s: stage }));
}

function renderDiary(snap) {
  const diary = (snap.research && snap.research.diary) || [];
  if (!diary.length) { fill("diary", el("p", { class: "hint" }, t("no_diary"))); return; }
  fill("diary", diary.slice(0, 10).map((e) => el("article", { class: "quest" },
    el("div", { class: "quest-head" }, el("span", { class: "quest-date" }, e.date), stageTag(e.stage)),
    e.tldr.length ? el("ul", {}, e.tldr.map((line) => el("li", {}, line))) : null,
    e.notes ? el("details", {}, el("summary", {}, t("notes")), el("pre", {}, e.notes)) : null)));
}

function cause(name) {
  return t("causes")[name] || name.replace(/[._]/g, " ");
}

function renderLab(snap) {
  const gate = snap.gate || [];
  $("lab-stats").textContent = t("lab_stats", { tried: gate.length, promoted: gate.filter((g) => g.promoted).length });
  const live = snap.strategies && snap.strategies.live;
  fill("champion", el("span", { class: "crown", "aria-hidden": "true" }, "👑"),
    el("div", {}, el("div", { class: "label" }, t("champion")), el("div", { class: "name" }, live || "?"),
      el("div", { class: "hint" }, t("champion_since"))));
  const graves = gate.filter((g) => !g.passed);
  fill("graveyard", graves.length ? graves.map((g) => {
    const m = g.in_sample;
    return el("div", { class: "tomb" },
      el("div", { class: "rip" }, t("rip")),
      el("div", { class: "name" }, g.strategy || "?"),
      el("div", { class: "date" }, shortDate(g.time)),
      el("div", { class: "cause" }, g.failed.map(cause).join(", ")),
      m ? el("div", { class: "stats" }, t("in_sample_stats", { profit: pct(m.profit_pct), pf: num(m.profit_factor), dd: pct(m.max_drawdown, false) })) : null);
  }) : el("p", { class: "empty" }, t("no_graves")));
}

function copyButton(text) {
  const btn = el("button", { type: "button", class: "copy" }, t("copy"));
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = t("copied");
      setTimeout(() => { btn.textContent = t("copy"); }, 1500);
    } catch (_) { /* clipboard blocked: the address is still selectable */ }
  });
  return btn;
}

function safeQr(path) {
  // Only local images under qr/, so a typo in site.json cannot point the page elsewhere.
  return typeof path === "string" && /^qr\/[\w.-]+\.(png|jpe?g|webp|svg)$/i.test(path) ? path : null;
}

function renderFeed(snap, site) {
  const eco = economy(snap, site);
  const coffee = Number(site.coffee_usd) || 2;
  $("coffee-price").textContent = usd(coffee);
  $("coffee-line").textContent = eco.monthly ? t("coffee", { hours: Math.round(coffee / (eco.monthly * 12 / 365 / 24)) }) : "";
  fill("costs", (site.costs_usd_per_month || []).map((c) => el("li", {}, `${c.name}: ${usd(Number(c.usd))}/${t("per_month")}`)));

  const donate = site.donate || {};
  const cards = [];
  for (const w of donate.crypto || []) {
    if (!w.address) continue;
    const qr = safeQr(w.qr);
    cards.push(el("div", { class: "wallet" }, el("div", { class: "label" }, w.label),
      el("div", { class: "addr" }, el("code", {}, w.address), copyButton(w.address)),
      qr ? el("img", { src: qr, alt: `QR ${w.label}`, width: "168", height: "168", loading: "lazy" }) : null));
  }
  for (const b of donate.bank || []) {
    // A QR alone is enough (e.g. Momo), so the account number need not be published as text.
    const qr = safeQr(b.qr);
    if (!b.account && !qr) continue;
    cards.push(el("div", { class: "wallet" }, el("div", { class: "label" }, b.label),
      el("div", { class: "who" }, [b.bank, b.name].filter(Boolean).join(" · ")),
      b.account ? el("div", { class: "addr" }, el("code", {}, b.account), copyButton(b.account)) : null,
      qr ? el("img", { src: qr, alt: `QR ${b.label}`, width: "168", height: "168", loading: "lazy" }) : null));
  }
  fill("donate", cards.length ? cards : el("p", { class: "hint" }, t("no_donate")));
  if (site.repo && /^https:\/\/github\.com\//.test(site.repo)) $("repo-link").href = site.repo;
}

function money(amount, currency) {
  if (currency === "VND") return isNum(amount) ? `${amount.toLocaleString(state.lang)} ₫` : "–";
  return currency === "USD" ? usd(amount) : usdt(amount, false);
}

function renderHall(snap, site) {
  const gifts = snap.donations || {};
  const items = gifts.items || [];
  $("hall-total").textContent = gifts.count ? t("hall_total", { n: gifts.count, total: usd(gifts.total_usd) }) : "";
  fill("donors", items.length ? items.map((d) => el("li", {},
    el("span", { class: "tag" }, "♥"),
    el("span", {}, el("span", { class: "who" }, d.who || t("anon")), el("span", { class: "side" }, d.via)),
    el("span", { class: "pnl gain" }, money(d.amount, d.currency)),
    el("span", { class: "meta" }, ago(parseDate(d.time))),
    d.note ? el("span", { class: "note" }, `“${d.note}”`) : null)) : el("li", { class: "empty" }, t("no_donors")));
  const eco = economy(snap, site);
  $("hall-cover").textContent = gifts.total_usd > 0 && eco.spent > 0
    ? t("hall_cover", { pct: pct(gifts.total_usd / eco.spent, false) }) : "";
}

function renderUpdated(snap) {
  const at = parseDate(snap && snap.generated_at);
  const stale = at && Date.now() - at.getTime() > 5 * 60_000;
  $("updated").textContent = state.error ? t("load_error") : at ? t(stale ? "stale" : "updated", { t: ago(at) }) : "";
}

function render() {
  renderStatic();
  const snap = state.snapshot || { bot: { online: false }, mood: "down" };
  const site = state.site || {};
  renderHero(snap, site);
  renderStats(snap);
  renderAchievements(snap, site);
  renderChart(snap);
  renderTrades(snap);
  renderDiary(snap);
  renderLab(snap);
  renderFeed(snap, site);
  renderHall(snap, site);
  renderUpdated(state.snapshot);
}

async function getJson(url) {
  const resp = await fetch(url, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
  return resp.json();
}

async function refresh() {
  try {
    const [snapshot, site] = await Promise.all([getJson("api/snapshot.json"), state.site || getJson("api/site.json")]);
    Object.assign(state, { snapshot, site, error: false });
  } catch (_) {
    state.error = true;
  }
  render();
}

for (const btn of document.querySelectorAll(".lang button")) {
  btn.addEventListener("click", () => {
    state.lang = btn.dataset.lang;
    try { localStorage.setItem("lang", state.lang); } catch (_) { /* storage blocked */ }
    $("bubble").dataset.full = ""; // retype the dialog in the new language
    render();
  });
}

refresh();
setInterval(refresh, REFRESH_MS);
