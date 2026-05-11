"""
KOSPI 시가총액 순위 수집기 (자동 증분 업데이트 버전)
설치: pip install finance-datareader pandas
사용: python3 collect_data.py
"""

import json
import os
import time
from datetime import datetime, timedelta
import FinanceDataReader as fdr

# ── 설정 ──────────────────────────────────────────
START_DATE = "20260101"   # 최초 수집 시작일 (rank_data.json 없을 때만 사용)
END_DATE   = "today"      # "today" = 오늘 날짜 자동
TOP_N      = 30           # 순위 몇 위까지
OUTPUT     = "rank_data.json"
# ──────────────────────────────────────────────────

# END_DATE 처리
if END_DATE == "today":
    END_DATE = datetime.today().strftime("%Y%m%d")

# 기존 데이터 있으면 마지막 날짜 다음부터만 수집
existing_data = None
if os.path.exists(OUTPUT):
    with open(OUTPUT, encoding="utf-8") as f:
        existing_data = json.load(f)
    last_date = existing_data["dates"][-1]
    next_date = (datetime.strptime(last_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    print(f"기존 데이터 발견 → 마지막: {last_date}, {next_date}부터 수집")
    START_DATE = next_date

# 이미 최신이면 종료
if START_DATE > END_DATE:
    print("이미 최신 데이터입니다. 종료.")
    exit(0)

def get_business_days(start: str, end: str):
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    days, cur = [], s
    while cur <= e:
        if cur.weekday() < 5:
            days.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return days

def collect(start: str, end: str, top_n: int) -> dict:
    print("KOSPI 종목 리스트 가져오는 중...")
    listing = fdr.StockListing('KOSPI')[['Code', 'Name', 'Marcap', 'Stocks']].dropna()
    listing = listing[listing['Marcap'] > 0].sort_values('Marcap', ascending=False)
    target = listing.head(top_n * 2).reset_index(drop=True)
    print(f"대상 종목 {len(target)}개 — 일별 주가 수집 시작")

    price_map = {}
    for i, row in target.iterrows():
        code, name, stocks = row['Code'], row['Name'], int(row['Stocks'])
        try:
            df = fdr.DataReader(code, start, end)[['Close']].dropna()
            if df.empty:
                continue
            df['marcap'] = df['Close'] * stocks
            price_map[name] = {'stocks': stocks, 'code': code, 'prices': df['marcap'].to_dict()}
            print(f"  [{i+1}/{len(target)}] {name} 완료 ({len(df)}일)")
        except Exception as e:
            print(f"  [{i+1}/{len(target)}] {name} 오류: {e}, 스킵")
        time.sleep(0.15)

    all_dates = sorted(set(
        str(d.date()) for v in price_map.values() for d in v['prices'].keys()
    ))
    print(f"\n총 {len(all_dates)}일 데이터 — 순위 계산 중...")

    rank_by_date = {}
    for date in all_dates:
        day_caps = []
        for name, info in price_map.items():
            cap = next((v for k, v in info['prices'].items() if str(k.date()) == date), None)
            if cap:
                day_caps.append({'name': name, 'ticker': info['code'], 'cap': int(cap)})
        day_caps.sort(key=lambda x: x['cap'], reverse=True)
        for rank, item in enumerate(day_caps[:top_n], 1):
            item['rank'] = rank
        rank_by_date[date.replace('-', '')] = day_caps[:top_n]

    return rank_by_date

def to_chart_format(rank_by_date: dict) -> dict:
    dates = sorted(rank_by_date.keys())
    companies = {}
    for date in dates:
        for entry in rank_by_date[date]:
            name = entry['name']
            if name not in companies:
                companies[name] = {'ranks': [], 'caps': [], 'ticker': entry['ticker']}
    for date in dates:
        appeared = {e['name']: e for e in rank_by_date[date]}
        for name in companies:
            if name in appeared:
                companies[name]['ranks'].append(appeared[name]['rank'])
                companies[name]['caps'].append(appeared[name]['cap'])
            else:
                companies[name]['ranks'].append(None)
                companies[name]['caps'].append(None)
    return {'dates': dates, 'companies': companies}

def merge(existing: dict, new: dict) -> dict:
    for date in new['dates']:
        if date in existing['dates']:
            continue
        existing['dates'].append(date)
        existing['dates'].sort()
        idx = existing['dates'].index(date)

        for name, info in new['companies'].items():
            new_rank = info['ranks'][new['dates'].index(date)]
            new_cap  = info['caps'][new['dates'].index(date)]
            if name not in existing['companies']:
                pad = [None] * (len(existing['dates']) - 1)
                existing['companies'][name] = {
                    'ranks': pad + [new_rank],
                    'caps':  pad + [new_cap],
                    'ticker': info['ticker']
                }
            else:
                existing['companies'][name]['ranks'].insert(idx, new_rank)
                existing['companies'][name]['caps'].insert(idx, new_cap)

        for name in existing['companies']:
            if name not in new['companies']:
                existing['companies'][name]['ranks'].insert(idx, None)
                existing['companies'][name]['caps'].insert(idx, None)

    return existing

if __name__ == "__main__":
    print(f"수집 시작: {START_DATE} ~ {END_DATE}, 상위 {TOP_N}위\n")
    raw = collect(START_DATE, END_DATE, TOP_N)

    if not raw:
        print("새로운 데이터가 없습니다. (공휴일이거나 장 미개장)")
    else:
        new_data = to_chart_format(raw)
        if existing_data:
            final = merge(existing_data, new_data)
            print("기존 데이터와 병합 완료")
        else:
            final = new_data

        # 최근 100일만 유지
        MAX_DAYS = 100
        if len(final['dates']) > MAX_DAYS:
            final['dates'] = final['dates'][-MAX_DAYS:]
            for name in final['companies']:
                final['companies'][name]['ranks'] = final['companies'][name]['ranks'][-MAX_DAYS:]
                final['companies'][name]['caps']  = final['companies'][name]['caps'][-MAX_DAYS:]
            print(f"최근 {MAX_DAYS}일로 데이터 정리 완료")

        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=2)
        print(f"\n저장 완료 → {OUTPUT}")
        print(f"  총 {len(final['dates'])}일, {len(final['companies'])}개 종목")
