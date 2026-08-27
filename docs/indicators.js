/* 보조지표 계산. 입력은 [{date, open, high, low, close}, ...] (날짜 오름차순),
   출력은 lightweight-charts 가 그대로 먹는 [{time, value}] 형태다.
   값이 아직 없는 앞 구간은 아예 점을 만들지 않는다(선이 0부터 그려지지 않게). */

function sma(rows, period, key = "close") {
  const out = [];
  let sum = 0;
  for (let i = 0; i < rows.length; i++) {
    const v = rows[i][key];
    if (v == null) return out;
    sum += v;
    if (i >= period) sum -= rows[i - period][key];
    if (i >= period - 1) out.push({ time: rows[i].date, value: sum / period });
  }
  return out;
}

function ema(values, period) {
  // values: [{time, value}] -> 같은 길이의 EMA. 초기값은 첫 period개의 단순평균.
  const out = [];
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) continue;
    if (prev === null) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += values[j].value;
      prev = sum / period;
    } else {
      prev = values[i].value * k + prev * (1 - k);
    }
    out.push({ time: values[i].time, value: prev });
  }
  return out;
}

function macd(rows, fast = 12, slow = 26, signal = 9) {
  const closes = rows.map(r => ({ time: r.date, value: r.close }));
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const byTime = new Map(fastEma.map(p => [p.time, p.value]));
  const line = slowEma
    .filter(p => byTime.has(p.time))
    .map(p => ({ time: p.time, value: byTime.get(p.time) - p.value }));
  const signalLine = ema(line, signal);
  const sigByTime = new Map(signalLine.map(p => [p.time, p.value]));
  const hist = line
    .filter(p => sigByTime.has(p.time))
    .map(p => ({ time: p.time, value: p.value - sigByTime.get(p.time) }));
  return { line, signal: signalLine, hist };
}

function rsi(rows, period = 14) {
  // Wilder 평활. 단순 평균만 쓰면 구간 끝에서 값이 튄다.
  const out = [];
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i < rows.length; i++) {
    const diff = rows[i].close - rows[i - 1].close;
    const gain = Math.max(diff, 0);
    const loss = Math.max(-diff, 0);
    if (i <= period) {
      avgGain += gain / period;
      avgLoss += loss / period;
      if (i < period) continue;
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
    }
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    out.push({ time: rows[i].date, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + rs) });
  }
  return out;
}

function ichimoku(rows, conv = 9, base = 26, spanB = 52) {
  // 선행스팬은 base 만큼 앞으로 밀어야 하는데, 미래 날짜는 데이터에 없다.
  // 마지막 날짜 이후로는 그리지 않고 있는 구간만 밀어서 그린다(구름 모양은 유지).
  const midpoint = (i, period) => {
    if (i < period - 1) return null;
    let hi = -Infinity, lo = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      hi = Math.max(hi, rows[j].high);
      lo = Math.min(lo, rows[j].low);
    }
    return (hi + lo) / 2;
  };

  const conversion = [], baseline = [], leadA = [], leadB = [];
  for (let i = 0; i < rows.length; i++) {
    const c = midpoint(i, conv);
    const b = midpoint(i, base);
    if (c != null) conversion.push({ time: rows[i].date, value: c });
    if (b != null) baseline.push({ time: rows[i].date, value: b });

    const shifted = i + base;           // base 만큼 앞으로 민 자리
    if (shifted < rows.length) {
      if (c != null && b != null) leadA.push({ time: rows[shifted].date, value: (c + b) / 2 });
      const sb = midpoint(i, spanB);
      if (sb != null) leadB.push({ time: rows[shifted].date, value: sb });
    }
  }
  return { conversion, baseline, leadA, leadB };
}
