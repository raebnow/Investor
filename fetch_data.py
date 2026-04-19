"""
GitHub Actions에서 실행 - 시장 데이터를 수집해 data.json으로 저장
pip install yfinance requests beautifulsoup4
"""
import json
from datetime import datetime, timezone

import requests
import yfinance as yf
from bs4 import BeautifulSoup

# ───── Yahoo Finance 심볼 ─────────────────────────────────────
YAHOO_SYMBOLS = {
    'dow':      '^DJI',
    'sp500':    '^GSPC',
    'nasdaq':   '^NDX',
    'russell':  '^RUT',
    'vix':      '^VIX',
    'kospi':    '^KS11',
    'kospi200': '^KS200',
    'gold':     'GC=F',
    'silver':   'SI=F',
    'copper':   'HG=F',
    'wti':      'CL=F',
    'brent':    'BZ=F',
    'natgas':   'NG=F',
}

FEAR_GREED_URL = 'https://feargreedchart.com/api/?action=all'
IG_NASDAQ_URL  = 'https://www.ig.com/en/indices/markets-indices/weekend-us-tech-100-e1'
IG_OIL_URL     = 'https://www.ig.com/en/indices/markets-indices/weekend-oil---us-crude'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
}


# ───── Yahoo Finance ──────────────────────────────────────────
def fetch_yahoo_all(symbols: dict) -> dict:
    results = {}
    try:
        tickers = yf.Tickers(' '.join(symbols.values()))
        for key, sym in symbols.items():
            try:
                fi    = tickers.tickers[sym].fast_info
                price = fi.last_price
                prev  = fi.previous_close
                if price is None or prev is None:
                    raise ValueError('가격 없음')
                change = price - prev
                pct    = (change / prev) * 100 if prev else 0.0
                results[key] = {
                    'price':  round(float(price),  4),
                    'change': round(float(change), 4),
                    'pct':    round(float(pct),    4),
                }
            except Exception as e:
                results[key] = {'error': str(e)}
    except Exception as e:
        for key in symbols:
            results[key] = {'error': str(e)}
    return results


# ───── CNN Fear & Greed ───────────────────────────────────────
def fetch_fear_greed() -> dict:
    try:
        resp = requests.get(FEAR_GREED_URL, timeout=15,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        j = resp.json()
        score = j.get('score', {}).get('score') or j.get('score', {}).get('overall_value')
        if score is None:
            return {'error': '점수 없음'}
        return {'score': int(score)}
    except Exception as e:
        return {'error': str(e)}


# ───── IG.com 스크래핑 ────────────────────────────────────────
IG_PRICE_SELS  = ['[data-field="BID"]', '[data-field="MID"]',
                   '.price-ticket__price', '.instrument-header__price',
                   '[class*="price__value"]']
IG_CHANGE_SELS = ['[data-field="CPT"]', '[data-field="CHG"]',
                   '.price-ticket__change-points']
IG_PCT_SELS    = ['[data-field="CPC"]', '[data-field="CHGP"]',
                   '.price-ticket__change-percentage']


def _sel_text(soup, sels):
    for sel in sels:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True).replace(',', '').replace('%', '').strip()
    return None


def fetch_ig_price(url: str) -> dict:
    try:
        sess = requests.Session()
        sess.headers.update(BROWSER_HEADERS)
        sess.get('https://www.ig.com/en/', timeout=10)
        resp = sess.get(url, timeout=20)
        if resp.status_code == 403:
            return {'error': 'IG 403 Forbidden'}
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        price_str  = _sel_text(soup, IG_PRICE_SELS)
        change_str = _sel_text(soup, IG_CHANGE_SELS)
        pct_str    = _sel_text(soup, IG_PCT_SELS)
        if price_str is None:
            return {'error': '주말에만 데이터 제공'}
        return {
            'price':  float(price_str),
            'change': float(change_str) if change_str else None,
            'pct':    float(pct_str)    if pct_str    else None,
        }
    except Exception as e:
        return {'error': str(e)}


# ───── 메인 ──────────────────────────────────────────────────
def main():
    print('Yahoo Finance 수집 중...')
    quotes = fetch_yahoo_all(YAHOO_SYMBOLS)
    for k, v in quotes.items():
        print(f'  {k}: {v}')

    print('Fear & Greed 수집 중...')
    fear_greed = fetch_fear_greed()
    print(f'  {fear_greed}')

    print('IG Weekend Nasdaq 수집 중...')
    ig_nasdaq = fetch_ig_price(IG_NASDAQ_URL)
    print(f'  {ig_nasdaq}')

    print('IG Weekend Oil 수집 중...')
    ig_oil = fetch_ig_price(IG_OIL_URL)
    print(f'  {ig_oil}')

    data = {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'quotes': quotes,
        'fear_greed': fear_greed,
        'weekend': {
            'nasdaq': ig_nasdaq,
            'oil':    ig_oil,
        }
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'\ndata.json 저장 완료: {data["updated"]}')


if __name__ == '__main__':
    main()
