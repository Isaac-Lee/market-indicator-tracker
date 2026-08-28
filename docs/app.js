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
// 섹터 순서가 곧 통합 뷰의 행 순서다. 한 섹터는 한 행을 통째로 쓰고, 그 안의 차트들이
// 폭을 똑같이 나눠 갖는다 — 섹터마다 개수가 달라도 행의 총 폭은 같다.
const SECTORS = [
  { title: "지수", charts: [
    { key: "kospi", icon: "🇰🇷",         label: "코스피",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 120 },
    { key: "kosdaq", icon: "🇰🇷",        label: "코스닥",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 120 },
    { key: "nasdaq", icon: "🇺🇸",        label: "나스닥",       type: "candle", unit: "pt",   digits: 2, ma: [5, 20, 60, 120], view: 100 },
  ]},
  { title: "종목", charts: [
    { key: "samsung_elec", icon: "📱",  label: "삼성전자",     type: "candle", unit: "원",   digits: 0, ma: [20, 60, 120], view: 110 },
    { key: "sk_hynix", icon: "💾",      label: "SK하이닉스",   type: "candle", unit: "원",   digits: 0, ma: [20, 60, 120], view: 110 },
    { key: "nvidia", icon: "🖥",        label: "엔비디아",     type: "candle", unit: "$",    digits: 2, ma: [21, 60, 120], view: 100 },
    { key: "oracle", icon: "☁️",        label: "오라클",       type: "candle", unit: "$",    digits: 2, ma: [21, 60], view: 100 },
  ]},
  { title: "환율", charts: [
    { key: "usdkrw", icon: "💵",        label: "원달러",       type: "candle", unit: "원",   digits: 2, ma: [5, 20, 60], view: 130 },
    { key: "usdjpy", icon: "💴",        label: "달러엔",       type: "candle", unit: "엔",   digits: 2, ma: [5, 20, 60], view: 130 },
  ]},
  { title: "원자재·코인", charts: [
    // 금은 1년 = 거래일 약 250봉, 비트코인은 주말도 열려서 1년 = 365봉이다.
    { key: "gold", icon: "🥇",          label: "금",           type: "candle", unit: "$",    digits: 1,
      ma: [5, 20, 60, 120], extras: ["ichimoku", "macd", "rsi"], view: 250 },
    { key: "wti", icon: "🛢",           label: "WTI 원유",     type: "candle", unit: "$",    digits: 2,
      ma: [5, 20, 60, 120], extras: ["macd", "rsi"], view: 126 },
    { key: "btc", icon: "🪙",           label: "비트코인",     type: "candle", unit: "$",    digits: 0,
      ma: [20, 60, 120], extras: ["macd", "rsi"], view: 365 },
  ]},
  { title: "금리", charts: [
    { key: "ktb3y", icon: "🇰🇷",         label: "국고채 3년",   type: "line",   unit: "%",    digits: 3, ma: [4, 12, 26, 52], view: 157 },
    { key: "ust10y", icon: "🇺🇸",        label: "미국채 10년",  type: "line",   unit: "%",    digits: 3, ma: [20, 60, 120], view: 750 },
  ]},
  // 누적 순매수는 세로로 눌리면 선이 겹쳐 읽히지 않는다. 맨 아래에서 4:3으로 그린다.
  { title: "수급", charts: [
    { key: "investor_flow", id: "foreign_flow", icon: "🌏", label: "외국인 순매수",
      type: "flow", digits: 0, view: 105, ratio: true, lines: [
        { col: "foreign_cum",      name: "외국인 누적", color: "#e0504a", width: 2 },
        { col: "foreign_cum_ma4w", name: "4w ma",       color: "#2962ff", width: 2 },
      ]},
    { key: "investor_flow", id: "investor_flow", icon: "👥", label: "주체별 순매수",
      type: "flow", digits: 0, view: 105, ratio: true, lines: [
        { col: "foreign_cum",     name: "외국인", color: "#e0504a", width: 2 },
        { col: "institution_cum", name: "기관",   color: "#2962ff", width: 2 },
        { col: "individual_cum",  name: "개인",   color: "#22a06b", width: 2 },
        { col: "pension_cum",     name: "연기금", color: "#8b7fd4", width: 1 },
      ]},
  ]},
];

// 탭/해시가 가리키는 이름. 같은 계열을 다르게 그리는 카드가 있어 key 로는 부족하다.
for (const sector of SECTORS) for (const spec of sector.charts) spec.id ||= spec.key;

const CHARTS = SECTORS.flatMap(s => s.charts);

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
    // 페이지를 스크롤하다가 커서가 차트 위를 지나면 휠이 차트 확대로 먹혀서
    // 보고 있던 구간이 멋대로 바뀐다. 확대·이동을 통째로 끄고 고정 구간만 본다.
    handleScroll: false,
    handleScale: false,
  };
}

/* ---------------------------------------------------------------- 카드 */

function buildCard(spec, tall) {
  const rows = (DATA.series[spec.key] || []).filter(r => r.close != null || spec.type === "flow");
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-head">
      <span class="card-title"><span class="ico">${spec.icon || ""}</span>${spec.label}</span>
      <span class="card-last"></span>
    </div>
    <div class="legend"></div>
    <div class="chart-wrap${spec.ratio ? " ratio" : ""}"><div class="tooltip"></div></div>`;

  const wrap = card.querySelector(".chart-wrap");
  const tooltip = card.querySelector(".tooltip");
  const legend = card.querySelector(".legend");

  const extras = spec.extras || [];
  const paneCount = 1 + extras.filter(e => e === "macd" || e === "rsi").length;
  // ratio 차트는 높이를 CSS(aspect-ratio)가 정하고 autoSize가 따라간다.
  const height = spec.ratio ? undefined
    : (tall ? 460 : 260) + (paneCount - 1) * (tall ? 140 : 84);

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
    for (const line of spec.lines) {
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
      for (const l of spec.lines) body += line(l.name, fmtFlow(row[l.col]) + "원");
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

/* 탭 이름: "all"(전 섹터) | "sector:<제목>"(그 섹터 전체) | 차트 id(하나만) */

const sectorTab = title => "sector:" + title;

function sectorBlock(app, sector, tall) {
  const heading = document.createElement("h2");
  heading.className = "sector";
  heading.textContent = sector.title;
  app.appendChild(heading);

  // 한 섹터 = 한 행. 카드가 flex: 1 이라 개수가 달라도 행 전체 폭은 같다.
  const row = document.createElement("div");
  row.className = "row";
  app.appendChild(row);
  for (const spec of sector.charts) row.appendChild(buildCard(spec, tall));
}

function render(tab) {
  for (const chart of charts.splice(0)) chart.remove();

  const app = document.getElementById("app");
  app.innerHTML = "";

  if (tab === "all") {
    for (const sector of SECTORS) sectorBlock(app, sector, false);
  } else if (tab.startsWith("sector:")) {
    // 섹터 하나만 볼 때는 카드가 몇 장 없으니 크게 그린다.
    const sector = SECTORS.find(s => sectorTab(s.title) === tab);
    if (sector) sectorBlock(app, sector, sector.charts.length <= 2);
  } else {
    const row = document.createElement("div");
    row.className = "row";
    app.appendChild(row);
    const spec = CHARTS.find(c => c.id === tab);
    if (spec) row.appendChild(buildCard(spec, true));
  }

  // nav 와 picker 가 같은 tab 을 가리키므로 선택 표시는 한 번에 갱신한다.
  for (const btn of document.querySelectorAll("[data-tab]")) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  }
  markPicker(tab);
  closePicker();
  location.hash = tab;
}

/* ------------------------------------------------------------ 선택 UI */

/** 그 탭이 속한 섹터. "all" 은 어디에도 속하지 않는다. */
const sectorOf = tab => SECTORS.find(
  s => sectorTab(s.title) === tab || s.charts.some(c => c.id === tab));

const tabLabel = tab => {
  if (tab === "all") return "통합";
  const sector = SECTORS.find(s => sectorTab(s.title) === tab);
  if (sector) return sector.title + " 전체";
  const spec = CHARTS.find(c => c.id === tab);
  return spec ? (spec.icon ? spec.icon + " " : "") + spec.label : "통합";
};

/** 접혀 있어도 무엇을 보고 있는지 알 수 있게 가운데에 적어 둔다. 통합일 때도
 *  비우지 않는다 — 빈칸이면 표시가 없는 것인지 아무것도 안 고른 것인지 모른다. */
function markPicker(tab) {
  const current = document.querySelector(".picker-current");
  if (!current) return;
  current.textContent = tab === "all" ? "모든 지표 보는 중" : `${tabLabel(tab)} 보는 중`;
}

function closePicker() {
  const picker = document.getElementById("picker");
  if (!picker) return;
  picker.classList.remove("open");
  const burger = picker.querySelector(".burger");
  if (burger) burger.setAttribute("aria-expanded", "false");
}

function makeButton(tab, label, cls) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  btn.dataset.tab = tab;
  if (cls) btn.className = cls;
  btn.onclick = () => render(tab);
  return btn;
}

const chartLabel = spec => (spec.icon ? spec.icon + " " : "") + spec.label;

/** 열린 메뉴가 화면 아래로 넘치지 않게 높이를 실제로 보이는 만큼만 준다.
 *
 *  iOS 사파리는 주소창·제어바가 떠 있어도 vh 를 "그것들이 없을 때" 기준으로 잡아서,
 *  70vh 로 두면 패널 아래끝이 제어바 밑에 깔린다. 스크롤을 끝까지 내려도 마지막 줄에
 *  손가락이 닿지 않는다. visualViewport 는 지금 눈에 보이는 높이를 준다. */
function sizePanel(panel) {
  const view = window.visualViewport;
  const height = view ? view.height : window.innerHeight;
  const offset = view ? view.offsetTop : 0;
  const top = panel.getBoundingClientRect().top;
  const margin = 12;
  panel.style.maxHeight = `${Math.max(200, height + offset - top - margin)}px`;
}

/** 스크롤 위치에 따라 좌우 화살표를 켜고 끈다. 양쪽 다 없으면 아예 감춘다. */
function markScrollEdges(shell, scroller) {
  const max = scroller.scrollWidth - scroller.clientWidth;
  shell.classList.toggle("at-start", scroller.scrollLeft <= 2);
  shell.classList.toggle("at-end", scroller.scrollLeft >= max - 2);
  shell.classList.toggle("no-scroll", max <= 2);
}

function buildTabs() {
  // ---- 넓은 화면: 한 줄. 통합만 왼쪽에 고정하고 섹터는 좌우로 민다.
  const nav = document.getElementById("tabs");
  nav.appendChild(makeButton("all", "통합", "sector-btn all-btn"));

  const shell = document.createElement("div");
  shell.className = "tab-shell";
  nav.appendChild(shell);

  const scroller = document.createElement("div");
  scroller.className = "tab-scroll";
  shell.appendChild(scroller);

  for (const sector of SECTORS) {
    // 섹터 버튼이 그 섹터의 지표 버튼들을 이끈다. 묶음 사이를 세로선으로 끊어서
    // 어느 지표가 어느 섹터에 속하는지 줄만 보고도 알 수 있게 한다.
    const group = document.createElement("div");
    group.className = "tab-group";
    group.appendChild(makeButton(sectorTab(sector.title), sector.title, "sector-btn"));
    for (const spec of sector.charts) {
      group.appendChild(makeButton(spec.id, chartLabel(spec)));
    }
    scroller.appendChild(group);
  }

  // 화살표는 표시이자 버튼이다. 누르면 화면 폭의 4/5 만큼 민다.
  const arrow = (dir, glyph) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `tab-arrow tab-arrow-${dir}`;
    btn.setAttribute("aria-label", dir === "left" ? "이전 지표" : "다음 지표");
    btn.textContent = glyph;
    btn.onclick = () => scroller.scrollBy({
      left: (dir === "left" ? -1 : 1) * scroller.clientWidth * 0.8,
      behavior: "smooth",
    });
    shell.appendChild(btn);
    return btn;
  };
  arrow("left", "‹");
  arrow("right", "›");

  const syncEdges = () => markScrollEdges(shell, scroller);
  scroller.addEventListener("scroll", syncEdges, { passive: true });
  window.addEventListener("resize", syncEdges);
  syncEdges();

  // ---- 좁은 화면: 햄버거 하나로 접는다. 23개를 어떤 식으로 늘어놓아도
  // 화면 위쪽을 통째로 먹거나 옆으로 숨는다.
  const picker = document.getElementById("picker");

  // 통합은 늘 왼쪽에 두고 눈에 띄게 칠해 둔다 — 어디까지 파고들었든 돌아올 자리.
  picker.appendChild(makeButton("all", "통합", "picker-home"));

  const current = document.createElement("span");
  current.className = "picker-current";
  picker.appendChild(current);

  const burger = document.createElement("button");
  burger.type = "button";
  burger.className = "burger";
  burger.setAttribute("aria-label", "지표 선택");
  burger.setAttribute("aria-expanded", "false");
  burger.innerHTML = "<span></span><span></span><span></span>";
  burger.onclick = () => {
    const open = picker.classList.toggle("open");
    burger.setAttribute("aria-expanded", String(open));
    if (open) sizePanel(panel);
  };
  picker.appendChild(burger);

  const panel = document.createElement("div");
  panel.className = "picker-panel";
  panel.appendChild(makeButton("all", "통합", "picker-item picker-lead"));
  for (const sector of SECTORS) {
    const group = document.createElement("div");
    group.className = "picker-group";
    group.appendChild(
      makeButton(sectorTab(sector.title), sector.title + " 전체", "picker-item picker-lead"));
    const list = document.createElement("div");
    list.className = "picker-list";
    for (const spec of sector.charts) {
      list.appendChild(makeButton(spec.id, chartLabel(spec), "picker-item"));
    }
    group.appendChild(list);
    panel.appendChild(group);
  }
  picker.appendChild(panel);

  // 주소창·제어바는 스크롤하다 보면 접혔다 펴진다. 그때마다 보이는 높이가 달라지므로
  // 열려 있는 동안 다시 재 준다.
  const resize = () => { if (picker.classList.contains("open")) sizePanel(panel); };
  window.addEventListener("resize", resize);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", resize);
    window.visualViewport.addEventListener("scroll", resize);
  }

  // 바깥을 누르거나 Esc 를 누르면 닫는다. 열어둔 채로 스크롤하면 시야를 가린다.
  document.addEventListener("pointerdown", e => {
    // target 이 늘 Element 인 것은 아니다(document, 텍스트 노드 등).
    const el = e.target instanceof Element ? e.target : null;
    if (!el || !el.closest("#picker")) closePicker();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closePicker();
  });
}
function isKnownTab(tab) {
  return tab === "all"
    || SECTORS.some(s => sectorTab(s.title) === tab)
    || CHARTS.some(c => c.id === tab);
}

async function main() {
  DATA = await (await fetch("data.json")).json();
  // 숫자는 계기판처럼, 라벨은 그 옆에 흐리게. 스타일은 style.css 의 #generated.
  const stamp = DATA.generated.slice(0, 16).replace("T", " ");
  document.getElementById("generated").innerHTML =
    `<span class="stamp-key">갱신</span>` +
    `<span class="stamp-value">${stamp}</span>` +
    `<span class="stamp-key">KST</span>`;
  buildTabs();
  const initial = decodeURIComponent(location.hash.slice(1));
  render(isKnownTab(initial) ? initial : "all");
}

main();
