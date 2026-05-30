"""자막(해설) 수집 — build_dataset.py 로 이미지 다 뽑은 뒤에 따로 실행.

하는 일:
 1) output/has_heatmap, output/no_heatmap 의 highlights.csv 에 있는 영상들의
    한국어 타임코드 자막(json3)을 받아 transcripts/{video_id}.json 로 저장
 2) 각 이미지 시점(start_time_sec) 앞뒤 PAD초에 겹치는 해설을 골라
    highlights_text.csv 로 (transcript_text, transcript_lang 컬럼 추가) 저장

특징: 요청 간 텀 + 429 시 대기·재시도 + 이미 받은 영상 건너뛰기(이어하기).

실행:
    $env:PATH = "C:\\Users\\kimyb\\.deno\\bin;$env:PATH"
    python fetch_transcripts.py
"""
import os
import csv
import json
import time
import urllib.request
import yt_dlp

CSV_DIRS = ['output/has_heatmap', 'output/no_heatmap']
TDIR = 'transcripts'           # 영상별 전체 자막 저장 폴더
LANGS = ('ko',)
PAD = 15                        # 이미지 시점 앞뒤 맥락 윈도우(초)
SLEEP = 3                       # 영상 간 기본 텀(초)
RL_WAIT = 90                    # 429(rate-limit) 시 대기(초)
RETRIES = 3

YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'remote_components': ['ejs:github'],
    'sleep_interval_requests': 2,
}

def parse_json3(raw_bytes):
    data = json.loads(raw_bytes)
    out = []
    for ev in data.get('events', []):
        if 'segs' not in ev:
            continue
        text = ''.join(s.get('utf8', '') for s in ev['segs']).strip()
        if not text:
            continue
        start = ev.get('tStartMs', 0) / 1000.0
        dur = ev.get('dDurationMs', 0) / 1000.0
        out.append({'start': start, 'end': start + dur, 'text': text})
    return out

def get_transcript(info):
    """수동 자막 우선, 없으면 자동생성. (리스트, 언어태그) 반환."""
    for key, suffix in [('subtitles', ''), ('automatic_captions', '(auto)')]:
        subs = info.get(key) or {}
        for lang in LANGS:
            if lang not in subs:
                continue
            url = next((f['url'] for f in subs[lang] if f.get('ext') == 'json3'), None)
            if not url:
                continue
            raw = urllib.request.urlopen(url, timeout=30).read()
            return parse_json3(raw), f'{lang}{suffix}'
    return [], 'none'

def is_ratelimit(msg):
    msg = (msg or '').lower()
    return '429' in msg or 'rate-limit' in msg or 'too many requests' in msg

def text_in_window(transcript, w_start, w_end):
    return ' '.join(c['text'] for c in transcript
                    if c['end'] >= w_start and c['start'] <= w_end)

def collect_videos():
    """두 CSV에서 (video_id, url) 유니크 목록."""
    seen, items = set(), []
    for d in CSV_DIRS:
        path = os.path.join(d, 'highlights.csv')
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                vid = row['video_id']
                if vid not in seen:
                    seen.add(vid)
                    items.append((vid, row['video_url']))
    return items

def fetch_all():
    os.makedirs(TDIR, exist_ok=True)
    videos = collect_videos()
    print(f'자막 대상 영상: {len(videos)}개\n')
    done = ok = fail = 0
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        for i, (vid, url) in enumerate(videos, 1):
            out = os.path.join(TDIR, f'{vid}.json')
            if os.path.exists(out):       # 이어하기: 이미 받은 건 skip
                done += 1
                continue
            tr, lang = None, 'none'
            for attempt in range(1, RETRIES + 1):
                try:
                    info = ydl.extract_info(url, download=False)
                    tr, lang = get_transcript(info)
                    break
                except Exception as e:
                    if is_ratelimit(str(e)) and attempt < RETRIES:
                        print(f'  [{i}] 429 → {RL_WAIT}s 대기 후 재시도')
                        time.sleep(RL_WAIT)
                    else:
                        tr, lang = [], 'error'
                        break
            if tr is None:
                tr = []
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({'lang': lang, 'segments': tr}, f, ensure_ascii=False, indent=2)
            if tr:
                ok += 1
            else:
                fail += 1
            print(f'[{i}/{len(videos)}] {vid}  {lang}  {len(tr)}개 세그먼트')
            time.sleep(SLEEP)
    print(f'\n자막 저장 완료: 성공 {ok}, 빈자막/실패 {fail}, 건너뜀 {done} → {TDIR}/')

def enrich_csvs():
    """각 CSV에 transcript_text, transcript_lang 컬럼 추가해 highlights_text.csv 로 저장."""
    cache = {}
    def load(vid):
        if vid not in cache:
            p = os.path.join(TDIR, f'{vid}.json')
            if os.path.exists(p):
                d = json.load(open(p, encoding='utf-8'))
                cache[vid] = (d.get('segments', []), d.get('lang', 'none'))
            else:
                cache[vid] = ([], 'none')
        return cache[vid]

    for d in CSV_DIRS:
        src = os.path.join(d, 'highlights.csv')
        if not os.path.exists(src):
            continue
        rows = list(csv.DictReader(open(src, encoding='utf-8-sig')))
        for r in rows:
            seg, lang = load(r['video_id'])
            s = int(r['start_time_sec'])
            e = int(r.get('end_time_sec') or s)
            r['transcript_text'] = text_in_window(seg, max(0, s - PAD), e + PAD)
            r['transcript_lang'] = lang
        if not rows:
            continue
        dst = os.path.join(d, 'highlights_text.csv')
        with open(dst, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f'CSV 확장 저장: {dst}')

if __name__ == '__main__':
    fetch_all()
    enrich_csvs()
