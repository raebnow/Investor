"""
GitHub Actions에서 실행 - 시장 데이터를 수집해 data.json으로 저장
pip install yfinance requests beautifulsoup4
"""
import json
import re
from datetime import datetime, timezone

import requests
import yfinance as yf
from bs4 import BeautifulSoup

# ───── investing.com 설정 ──────────────────────────────────────
INV_INDICES_URL    = 'https://www.investing.com/indices/indices-futures'
INV_COMMODITIES_URL = 'https://www.investing.com/commodities/real-time-futures'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
}

# ───── investing.com name → 내부 key 매핑 ──────────────────────
INDEX_NAME_MAP = {
    'US 30':          'dow',
    'US 500':         'sp500',
    'US Tech 100':    'nasdaq',
    'Small Cap 2000': 'russell',
    'S&P 500 VIX':    'vix',
}

COMMODITY_NAME_MAP = {
    'Gold':         'gold',
    'Silver':       'silver',
    'Copper':       'copper',
    'Crude Oil WTI': 'wti',
    'Brent Oil':    'brent',
    'Natural Gas':  'natgas',
}

# ───── KOSPI (Yahoo Finance) ──────────────────────────────────
KOSPI_SYMBOLS = {
    'kospi':    '^KS11',
    'kospi200': '^KS200',
}

# ───── IG Weekend 설정 ────────────────────────────────────────
IG_NASDAQ_URL = 'https://www.ig.com/en/indices/markets-indices/weekend-us-tech-100-e1'
IG_OIL_URL    = 'https://www.ig.com/en/indices/markets-indices/weekend-oil---us-crude'
FEAR_GREED_URL = 'https://feargreedchart.com/api/?action=all'


# ───── investing.com __NEXT_DATA__ 파싱 ──────────────────────
def _fetch_next_data(url: str) -> dict:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  resp.text, re.DOTALL)
    if not m:
        raise ValueError('__NEXT_DATA__ not found')
    return json.loads(m.group(1))


def _extract_collection(next_data: dict) -> list:
    """__NEXT_DATA__ state에서 _collection 배열을 찾아 반환."""
    state = next_data.get('props', {}).get('pageProps', {}).get('state', {})

    # commodities 페이지: assetsCollectionStore.assetsCollection._collection
    ac = state.get('assetsCollectionStore', {}).get('assetsCollection', {})
    if '_collection' in ac and ac['_collection']:
        return ac['_collection']

    # indices 페이지: multiAssetsCollectionStore.multiAssetsCollections.*._collection
    colls = state.get('multiAssetsCollectionStore', {}).get('multiAssetsCollections', {})
    for coll_val in colls.values():
        if isinstance(coll_val, dict) and coll_val.get('_collection'):
            return coll_val['_collection']

    return []


def fetch_investing_data(url: str, name_map: dict) -> dict:
    results = {}
    try:
        nd = _fetch_next_data(url)
        collection = _extract_collection(nd)
        if not collection:
            raise ValueError('collection empty')
        by_name = {}
        for item in collection:
            name = item.get('name', '')
            if name not in by_name:  # first occurrence wins (e.g. CMX Copper over LME)
                by_name[name] = item
        for inv_name, key in name_map.items():
            item = by_name.get(inv_name)
            if not item:
                results[key] = {'error': f'{inv_name} not found'}
                continue
            last   = item.get('last')
            change = item.get('changeOneDay')
            pct    = item.get('changeOneDayPercent')
            if last is None:
                results[key] = {'error': '가격 없음'}
                continue
            results[key] = {
                'price':  round(float(last),   4),
                'change': round(float(change), 4) if change is not None else None,
                'pct':    round(float(pct),    4) if pct    is not None else None,
            }
    except Exception as e:
        for key in name_map.values():
            results[key] = {'error': str(e)}
    return results


# ───── Yahoo Finance (KOSPI only) ────────────────────────────
def fetch_yahoo_kospi(symbols: dict) -> dict:
    results = {}
    try:
        tickers = yf.Tickers(' '.join(symbols.values()))
        for key, sym in symbols.items():
            try:
                t  = tickers.tickers[sym]
                fi = t.fast_info
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
    print('investing.com 지수 수집 중...')
    idx_quotes = fetch_investing_data(INV_INDICES_URL, INDEX_NAME_MAP)
    for k, v in idx_quotes.items():
        print(f'  {k}: {v}')

    print('investing.com 원자재 수집 중...')
    com_quotes = fetch_investing_data(INV_COMMODITIES_URL, COMMODITY_NAME_MAP)
    for k, v in com_quotes.items():
        print(f'  {k}: {v}')

    print('Yahoo Finance (KOSPI) 수집 중...')
    kospi_quotes = fetch_yahoo_kospi(KOSPI_SYMBOLS)
    for k, v in kospi_quotes.items():
        print(f'  {k}: {v}')

    quotes = {**idx_quotes, **com_quotes, **kospi_quotes}

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
