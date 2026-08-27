/* 탭 하나당 차트 하나, "통합"은 전부 한 화면에. 차트 정의는 CHARTS 한 곳에만 둔다. */

const LWC = LightweightCharts;

// 기간별로 색을 고정한다. 차트마다 이동평균 조합이 달라도 같은 기간이면 같은 색이라
// 여러 카드를 훑을 때 선을 다시 읽지 않아도 된다. 주간 차트는 4/12/26/52가 같은 자리다.
const MA_COLOR = {
  4: "#7d8590", 5: "#7d8590",
  12: "#22a06b", 20: "#22a06b", 21: "#22a06b",
  26: "#e0504a", 60: "#e0504a",
  52: "#2962ff", 120: "#2962ff",
};
const MA_FALLBACK = "#c86dd7";

// type: candle(OHLC) | line(종가만) | flow(누적 순매수)
// ma: 이동평균 기간들, extras: ichimoku / macd / rsi
// view: 처음에 보여줄 마지막 봉 개수. 이동평균은 그 앞 데이터까지 먹고 계산하되
//       화면은 최근 구간만 잡는다 — 전 구간을 한 화면에 넣으면 최근 움직임이 뭉갠다.
// 텔레그램 일일 브리핑(notify_daily.py BRIEFING_GROUPS)에 나오는 계열만 그린다.
// data/ 에는 다른 계열도 쌓이지만 매일 눈으로 보는 것만 차트로 둔다.
const CHARTS = [
  { key: "kospi",         label: "코스피",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 120 },
  { key: "kosdaq",        label: "코스닥",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 120 },
  { key: "nasdaq",        label: "나스닥",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 100 },
  { key: "samsung_elec",  label: "삼성전자",     type: "candle", unit: "원",   digits: 0, ma: [20, 60, 120], view: 110 },
  { key: "sk_hynix",      label: "SK하이닉스",   type: "candle", unit: "원",   digits: 0, ma: [20, 60, 120], view: 110 },
  { key: "nvidia",        label: "엔비디아",     type: "candle", unit: "$",    digits: 2, ma: [21, 60, 120], view: 100 },
  { key: "oracle",        label: "오라클",       type: "candle", unit: "$",    digits: 2, ma: [21, 60], view: 100 },
  { key: "usdkrw",        label: "원달러",       type: "candle", unit: "원",   digits: 2, ma: [5, 20, 60], view: 130 },
  { key: "usdjpy",        label: "달러엔",       type: "candle", unit: "엔",   digits: 2, ma: [5, 20, 60], view: 130 },
  { key: "gold",          label: "금",           type: "candle", unit: "$",    digits: 1,
    ma: [5, 20, 60, 120], extras: ["ichimoku", "macd", "rsi"], view: 100 },
  { key: "wti",           label: "WTI 원유",     type: "candle", unit: "$",    digits: 2,
    ma: [5, 20, 60, 120], extras: ["macd", "rsi"], view: 120 },
  { key: "ktb3y",         label: "국고채 3년",   type: "line",   unit: "%",    digits: 3, ma: [4, 12, 26, 52], view: 157 },
  { key: "ust10y",        label: "미국채 10년",  type: "line",   unit: "%",    digits: 3, ma: [20, 60, 120], view: 750 },
  { key: "investor_flow", label: "주체별 순매수", type: "flow",   unit: "백만원", digits: 0, view: 105 },
];

const FLOW_LINES = [
  { col: "foreign_cum",     name: "외국인", color: "#e0504a", width: 2 },
  { col: "institution_cum", name: "기관",   color: "#2962ff", width: 2 },
  { col: "individual_cum",  name: "개인",   color: "#22a06b", width: 2 },
  { col: "pension_cum",     name: "연기금", color: "#8b7fd4", width: 1 },
  { col: "foreign_cum_ma4w", name: "외국인 4w ma", color: "#f0a04a", width: 1 },
];

let DATA = null;
const charts = [];   // 열려 있는 차트들 — 리사이즈/정리에 쓴다

const css = name => getComputedStyle(document.body).getPropertyValue(name).trim();
const fmt = (v, digits) =>
  v == null || Number.isNaN(v) ? "—" : v.toLocaleString("ko-KR",
    { minimumFractionDigits: digits, maximumFractionDigits: digits });

// 순매수는 백만원 단위로 들어온다. 누적이 수억 단위 숫자라 그대로 두면 자릿수를 세게 된다.
const fmtFlow = v => {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + "조";
  return (v / 100).toFixed(0) + "억";
};

function themeOptions() {
  return {
    layout: {
      background: { color: "transparent" },
      textColor: css("--muted"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: css("--grid") },
      horzLines: { color: css("--grid") },
    },
    localization: {
      locale: "ko-KR",
      // 기본 포맷은 눈금 종류에 따라 "10일"처럼 일(day)만 남겨서 어느 달인지 알 수 없다.
      timeFormatter: t => t,
    },
    rightPriceScale: { borderColor: css("--border") },
    timeScale: {
      borderColor: css("--border"),
      rightOffset: 4,
      tickMarkFormatter: (time, tickType) => {
        const [y, m, d] = String(time).split("-");
        if (tickType === LWC.TickMarkType.Year) return `${y}`;
        if (tickType === LWC.TickMarkType.Month) return `${y.slice(2)}.${m}`;
        return `${m}/${d}`;
      },
    },
    crosshair: {
      mode: LWC.CrosshairMode.Normal,
      vertLine: { color: css("--muted"), width: 1, style: 2, labelBackgroundColor: css("--accent") },
      horzLine: { color: css("--muted"), width: 1, style: 2, labelBackgroundColor: css("--accent") },
    },
  };
}

/* ---------------------------------------------------------------- 카드 */

function buildCard(spec, tall) {
  const rows = (DATA.series[spec.key] || []).filter(r => r.close != null || spec.type === "flow");
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-head">
      <span class="card-title">${spec.label}</span>
      <span class="card-last"></span>
    </div>
    <div class="legend"></div>
    <div class="chart-wrap"><div class="tooltip"></div></div>`;

  const wrap = card.querySelector(".chart-wrap");
  const tooltip = card.querySelector(".tooltip");
  const legend = card.querySelector(".legend");

  const extras = spec.extras || [];
  const paneCount = 1 + extras.filter(e => e === "macd" || e === "rsi").length;
  const height = (tall ? 460 : 260) + (paneCount - 1) * (tall ? 140 : 84);

  const chart = LWC.createChart(wrap, { ...themeOptions(), height, autoSize: true });
  charts.push(chart);

  const legendItems = [];
  const addLegend = (name, color) => legendItems.push(
    `<span><span class="sw" style="background:${color}"></span>${name}</span>`);

  // ---- 메인 시리즈
  let main;
  if (spec.type === "candle") {
    main = chart.addSeries(LWC.CandlestickSeries, {
      upColor: css("--up"), downColor: css("--down"),
      borderUpColor: css("--up"), borderDownColor: css("--down"),
      wickUpColor: css("--up"), wickDownColor: css("--down"),
      priceFormat: { type: "price", precision: spec.digits, minMove: 1 / 10 ** spec.digits },
    });
    main.setData(rows.map(r => ({
      time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
    })));
  } else if (spec.type === "line") {
    // MA120 이 파랑이라 본선까지 accent 파랑으로 두면 어느 쪽이 실제 금리인지 헷갈린다.
    main = chart.addSeries(LWC.LineSeries, {
      color: css("--text"), lineWidth: 1,
      priceFormat: { type: "price", precision: spec.digits, minMove: 1 / 10 ** spec.digits },
    });
    main.setData(rows.map(r => ({ time: r.date, value: r.close })));
  } else {
    for (const line of FLOW_LINES) {
      const series = chart.addSeries(LWC.LineSeries, {
        color: line.color, lineWidth: line.width,
        priceFormat: { type: "custom", formatter: fmtFlow, minMove: 1 },
      });
      series.setData(rows.filter(r => r[line.col] != null)
                         .map(r => ({ time: r.date, value: r[line.col] })));
      addLegend(line.name, line.color);
      if (line.col === "foreign_cum") main = series;
    }
  }

  // ---- 이동평균
  const maSeries = [];
  if (spec.ma && spec.type !== "flow") {
    spec.ma.forEach(period => {
      const data = sma(rows, period);
      if (!data.length) return;
      const color = MA_COLOR[period] || MA_FALLBACK;
      const series = chart.addSeries(LWC.LineSeries, {
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(data);
      maSeries.push({ label: `MA${period}`, series, color });
      addLegend(`MA${period}`, color);
    });
  }

  // ---- 일목균형표 (전환선/기준선/구름)
  if (extras.includes("ichimoku")) {
    const ich = ichimoku(rows);
    const cloud = [
      ["전환선", ich.conversion, "#e05fa0"],
      ["기준선", ich.baseline, "#5a5f6a"],
      ["선행A", ich.leadA, "#66b98a"],
      ["선행B", ich.leadB, "#c9a227"],
    ];
    for (const [name, data, color] of cloud) {
      if (!data.length) continue;
      const series = chart.addSeries(LWC.LineSeries, {
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, lineStyle: name.startsWith("선행") ? 2 : 0,
      });
      series.setData(data);
      addLegend(name, color);
    }
  }

  // ---- 서브패널 (MACD / RSI)
  let pane = 1;
  if (extras.includes("macd")) {
    const m = macd(rows);
    const histSeries = chart.addSeries(LWC.HistogramSeries, {
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    }, pane);
    histSeries.setData(m.hist.map(p => ({
      time: p.time, value: p.value, color: p.value >= 0 ? css("--up") : css("--down"),
    })));
    const lineSeries = chart.addSeries(LWC.LineSeries,
      { color: "#e0504a", lineWidth: 1, priceLineVisible: false }, pane);
    lineSeries.setData(m.line);
    const sigSeries = chart.addSeries(LWC.LineSeries,
      { color: "#22a06b", lineWidth: 1, priceLineVisible: false }, pane);
    sigSeries.setData(m.signal);
    addLegend("MACD(12,26,9)", "#e0504a");
    pane++;
  }
  if (extras.includes("rsi")) {
    const series = chart.addSeries(LWC.LineSeries, {
      color: "#c86dd7", lineWidth: 1, priceLineVisible: false,
      priceFormat: { type: "price", precision: 1, minMove: 0.1 },
    }, pane);
    series.setData(rsi(rows));
    // 70/30 은 과매수·과매도 기준선. 값이 아니라 눈금이라 마지막 값 표시는 끈다.
    for (const level of [70, 30]) {
      series.createPriceLine({ price: level, color: css("--border"), lineWidth: 1,
                               lineStyle: 2, axisLabelVisible: false });
    }
    addLegend("RSI(14)", "#c86dd7");
    pane++;
  }
  const subPaneCount = pane - 1;

  legend.innerHTML = legendItems.join("");

  // ---- 마지막 값 + 전일 대비
  const last = rows[rows.length - 1];
  const prev = rows[rows.length - 2];
  const lastEl = card.querySelector(".card-last");
  if (last) {
    if (spec.type === "flow") {
      const cls = last.foreign_cum >= 0 ? "chg-up" : "chg-down";
      lastEl.innerHTML = `외국인 누적 <span class="${cls}">${fmtFlow(last.foreign_cum)}원</span>`;
    } else {
      const diff = prev ? last.close - prev.close : null;
      const pct = diff != null && prev.close ? (diff / prev.close) * 100 : null;
      const cls = diff == null ? "" : diff >= 0 ? "chg-up" : "chg-down";
      const chg = diff == null ? ""
        : ` <span class="${cls}">${diff >= 0 ? "▲" : "▼"}${fmt(Math.abs(diff), spec.digits)} (${pct.toFixed(2)}%)</span>`;
      lastEl.innerHTML = `${fmt(last.close, spec.digits)}${spec.unit}${chg}`;
    }
  }

  // ---- 호버 툴팁
  const byTime = new Map(rows.map(r => [r.date, r]));
  chart.subscribeCrosshairMove(param => {
    if (!param.time || !param.point ||
        param.point.x < 0 || param.point.y < 0 ||
        param.point.x > wrap.clientWidth || param.point.y > wrap.clientHeight) {
      tooltip.style.display = "none";
      return;
    }
    const row = byTime.get(param.time);
    if (!row) { tooltip.style.display = "none"; return; }

    const line = (k, v) => `<div class="t-row"><span>${k}</span><span>${v}</span></div>`;
    let body = `<div class="t-date">${row.date}</div>`;
    if (spec.type === "candle") {
      body += line("시가", fmt(row.open, spec.digits))
            + line("고가", fmt(row.high, spec.digits))
            + line("저가", fmt(row.low, spec.digits))
            + line("종가", fmt(row.close, spec.digits));
    } else if (spec.type === "line") {
      body += line("종가", fmt(row.close, spec.digits) + spec.unit);
    } else {
      for (const l of FLOW_LINES) body += line(l.name, fmtFlow(row[l.col]) + "원");
    }
    for (const ma of maSeries) {
      const v = param.seriesData.get(ma.series);
      if (v) body += line(ma.label, fmt(v.value, spec.digits));
    }
    tooltip.innerHTML = body;
    tooltip.style.display = "block";

    // 커서 반대쪽에 붙여서 캔들을 가리지 않게 한다.
    const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    let x = param.point.x + 16;
    if (x + w > wrap.clientWidth) x = param.point.x - w - 16;
    let y = param.point.y + 16;
    if (y + h > wrap.clientHeight) y = Math.max(0, param.point.y - h - 16);
    tooltip.style.left = Math.max(0, x) + "px";
    tooltip.style.top = y + "px";
  });

  // autoSize 로 폭·높이가 잡힌 뒤에 걸어야 한다. 붙기 전에 걸면 무시된다.
  const view = Math.min(spec.view || rows.length, rows.length);
  requestAnimationFrame(() => {
    // 탭을 빠르게 바꾸면 이 프레임이 도착하기 전에 차트가 제거돼 있을 수 있다.
    if (!charts.includes(chart)) return;
    chart.timeScale().setVisibleLogicalRange({ from: rows.length - view, to: rows.length + 2 });
    const subHeight = tall ? 130 : 78;
    for (let i = 1; i <= subPaneCount; i++) chart.panes()[i].setHeight(subHeight);
  });
  return card;
}

/* ---------------------------------------------------------------- 렌더 */

function render(tabKey) {
  for (const chart of charts.splice(0)) chart.remove();

  const app = document.getElementById("app");
  app.innerHTML = "";
  const grid = document.createElement("div");
  grid.className = tabKey === "all" ? "grid" : "grid single";
  app.appendChild(grid);

  const specs = tabKey === "all" ? CHARTS : CHARTS.filter(c => c.key === tabKey);
  for (const spec of specs) grid.appendChild(buildCard(spec, tabKey !== "all"));

  for (const btn of document.querySelectorAll("nav button")) {
    btn.classList.toggle("active", btn.dataset.key === tabKey);
  }
  location.hash = tabKey;
}

function buildTabs() {
  const nav = document.getElementById("tabs");
  const tabs = [{ key: "all", label: "통합" },
                ...CHARTS.map(c => ({ key: c.key, label: c.label }))];
  for (const tab of tabs) {
    const btn = document.createElement("button");
    btn.textContent = tab.label;
    btn.dataset.key = tab.key;
    btn.onclick = () => render(tab.key);
    nav.appendChild(btn);
  }
}

async function main() {
  DATA = await (await fetch("data.json")).json();
  document.getElementById("generated").textContent =
    "갱신 " + DATA.generated.slice(0, 16).replace("T", " ");
  buildTabs();
  const initial = location.hash.slice(1);
  render(CHARTS.some(c => c.key === initial) || initial === "all" ? initial : "all");
}

main();
