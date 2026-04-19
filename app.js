'use strict';

/*
 * 데이터 흐름:
 *   GitHub Actions (15분 주기) → fetch_data.py → data.json (같은 repo)
 *   브라우저 → fetch('data.json') → 렌더링 (CORS 없음, 같은 origin)
 */
const DATA_URL   = 'data.json';
const REFRESH_MS = 5 * 60 * 1000;   // 5분마다 data.json 재확인
const FEAR_URL   = 'https://feargreedchart.com/api/?action=all';

// data.json의 각 key → 카드 DOM id 매핑
const CARD_MAP = {
  dow:      { id: 'card-dow',     dec: 0 },
  sp500:    { id: 'card-sp500',   dec: 2 },
  nasdaq:   { id: 'card-nasdaq',  dec: 2 },
  russell:  { id: 'card-russell', dec: 2 },
  vix:      { id: 'card-vix',     dec: 2 },
  kospi:    { id: 'card-kospi',   dec: 2 },
  kospi200: { id: 'card-kospi200',dec: 2 },
  gold:     { id: 'card-gold',    dec: 2 },
  silver:   { id: 'card-silver',  dec: 3 },
  copper:   { id: 'card-copper',  dec: 4 },
  wti:      { id: 'card-wti',     dec: 2 },
  brent:    { id: 'card-brent',   dec: 2 },
  natgas:   { id: 'card-natgas',  dec: 3 },
};

/* ===== 숫자 포맷 ===== */
function fmt(val, dec = 2) {
  if (val == null || isNaN(val)) return '—';
  return Number(val).toLocaleString('en-US', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function fmtChange(change, pct, dec = 2) {
  if (change == null || isNaN(change)) return '—';
  const sign = change >= 0 ? '+' : '';
  return `${sign}${fmt(change, dec)} (${sign}${Number(pct).toFixed(2)}%)`;
}

/* ===== DOM helpers ===== */
function setCard(id, { price, change, pct, error, dec = 2 } = {}) {
  const card = document.getElementById(id);
  if (!card) return;
  card.classList.remove('loading', 'error');
  const priceEl  = card.querySelector('.card-price');
  const changeEl = card.querySelector('.card-change');
  if (error) {
    card.classList.add('error');
    priceEl.textContent  = '—';
    changeEl.textContent = error;
    changeEl.className   = 'card-change';
    return;
  }
  priceEl.textContent  = fmt(price, dec);
  changeEl.textContent = fmtChange(change, pct, dec);
  if (change == null || isNaN(change)) {
    changeEl.className = 'card-change';
  } else {
    changeEl.className = 'card-change ' + (Number(change) >= 0 ? 'positive' : 'negative');
  }
}

/* ===== Fear & Greed 렌더링 ===== */
function scoreToMeta(score) {
  if (score <= 24) return { state: 'extreme-fear', label: '극도 공포 (Extreme Fear)' };
  if (score <= 44) return { state: 'fear',         label: '공포 (Fear)' };
  if (score <= 55) return { state: 'neutral',      label: '중립 (Neutral)' };
  if (score <= 75) return { state: 'greed',        label: '탐욕 (Greed)' };
  return              { state: 'extreme-greed',    label: '극도 탐욕 (Extreme Greed)' };
}

function renderFearGreed(data) {
  const widget   = document.getElementById('fear-widget');
  const scoreEl  = document.getElementById('fear-score');
  const labelEl  = document.getElementById('fear-label');
  const markerEl = document.getElementById('fear-bar-marker');
  widget.classList.remove('loading');
  if (!data || data.error) {
    scoreEl.textContent  = '—';
    labelEl.textContent  = data?.error ?? '데이터 없음';
    markerEl.style.left  = '50%';
    widget.dataset.state = '';
    return;
  }
  const { score } = data;
  const { state, label } = scoreToMeta(score);
  widget.dataset.state = state;
  scoreEl.textContent  = score;
  labelEl.textContent  = label;
  markerEl.style.left  = `${score}%`;
}

/* ===== Fear & Greed 직접 fetch (브라우저 — CORS 허용됨) ===== */
async function fetchFearGreedDirect() {
  const resp = await fetch(FEAR_URL);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const j = await resp.json();
  const score = j?.score?.score ?? j?.score?.overall_value;
  if (score == null) throw new Error('점수 없음');
  return { score: Math.round(Number(score)) };
}

/* ===== 메인 갱신 ===== */
async function refreshAll() {
  document.getElementById('last-updated').textContent = '갱신 중...';

  /* data.json 로드 (GitHub Actions가 15분마다 갱신) */
  let marketData = null;
  try {
    const resp = await fetch(`${DATA_URL}?_t=${Date.now()}`);
    if (resp.ok) marketData = await resp.json();
  } catch (e) {
    console.warn('data.json 로드 실패:', e.message);
  }

  /* Fear & Greed 실시간 직접 fetch (feargreedchart.com은 CORS 허용) */
  const fearRes = await Promise.allSettled([fetchFearGreedDirect()]);

  /* ──── 시장 데이터 렌더링 ──── */
  if (marketData?.quotes) {
    for (const [key, cfg] of Object.entries(CARD_MAP)) {
      const q = marketData.quotes[key];
      if (!q) { setCard(cfg.id, { error: '데이터 없음' }); continue; }
      setCard(cfg.id, { ...q, dec: cfg.dec });
    }
  } else {
    for (const cfg of Object.values(CARD_MAP)) {
      setCard(cfg.id, { error: 'GitHub Actions 실행 후 반영됩니다' });
    }
  }

  /* ──── Fear & Greed ──── */
  const fg = fearRes[0];
  renderFearGreed(
    fg.status === 'fulfilled'
      ? fg.value
      : (marketData?.fear_greed ?? { error: fg.reason?.message })
  );

  /* ──── Weekend (data.json에서 — IG.com은 GitHub Actions 서버가 수집) ──── */
  const wn = marketData?.weekend?.nasdaq;
  const wo = marketData?.weekend?.oil;
  setCard('card-w-nasdaq', wn
    ? (wn.error ? { error: wn.error } : { ...wn, dec: 2 })
    : { error: 'GitHub Actions 실행 후 반영됩니다' }
  );
  setCard('card-w-oil', wo
    ? (wo.error ? { error: wo.error } : { ...wo, dec: 2 })
    : { error: 'GitHub Actions 실행 후 반영됩니다' }
  );

  /* ──── 갱신 시각 ──── */
  const dataTime = marketData?.updated
    ? `데이터: ${new Date(marketData.updated).toLocaleString('ko-KR')}`
    : '';
  document.getElementById('last-updated').textContent =
    `${dataTime ? dataTime + ' · ' : ''}조회: ${new Date().toLocaleTimeString('ko-KR')}`;
}

/* ===== 초기화 ===== */
document.getElementById('refresh-btn').addEventListener('click', refreshAll);
refreshAll();
setInterval(refreshAll, REFRESH_MS);
