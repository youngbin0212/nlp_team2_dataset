"""자막(해설) 수집 — build_dataset.py 로 이미지 다 뽑은 뒤에 따로 실행.

하는 일:
 1) output/*/highlights.csv 의 영상들의 한국어 타임코드 자막(json3)을
    transcripts/{video_id}.json 로 저장
 2) 각 이미지 시점(start_time_sec) ±PAD초에 겹치는 해설을 골라
    highlights_text.csv 로 (transcript_text, transcript_lang 추가) 저장

봇 차단 대응(이미지 빌드와 동일):
 - 봇 차단 연속 BOT_STOP회면 그 라운드 중단 → 길게 쉬고 재개 (사람처럼 띄엄띄엄)
 - 실패(봇/네트워크)는 파일을 안 남김 → 다음에 재시도 (이어하기)
 - 'error'로 잘못 저장된 옛 파일은 자동으로 다시 받음
 - 자막이 원래 없는 영상은 lang='none'으로 저장(재시도 안 함)

실행:
    $env:PATH = "C:\\Users\\kimyb\\.deno\\bin;$env:PATH"
    python fetch_transcripts.py
"""
import os
import csv
import json
import time
import random
import urllib.request
import yt_dlp

FOLDERS = ['has_heatmap', 'no_heatmap']

def _find_csv(name):
    """highlights.csv 를 하위폴더 안/밖 어디에 있든 찾는다."""
    for p in (f'output/{name}/highlights.csv', f'output/{name}_highlights.csv'):
        if os.path.exists(p):
            return p
    return None

TDIR = 'transcripts'
LANGS = ('ko',)
PAD = 15
SLEEP = 3
BOT_STOP = 8
COOLDOWN = (2400, 4800)   # 봇차단 시 40~80분
MAX_ROUNDS = 60

YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'ignore_no_formats_error': True,   # 자막만 필요 → 포맷 선택 실패해도 진행
    'remote_components': ['ejs:github'],
    'sleep_interval_requests': 2,
}
# 쿠키 파일 자동 선택: cookies.txt 또는 *cookies*.txt 중 '가장 최근' 것 사용
# (확장 기본 이름 www.youtube.com_cookies.txt 로 받아도 그대로 인식)
import glob as _glob
_ck = [c for c in set(_glob.glob('cookies.txt') + _glob.glob('*cookies*.txt'))
       if os.path.exists(c)]
if _ck:
    YDL_OPTS['cookiefile'] = max(_ck, key=os.path.getmtime)
    print(f'쿠키 사용: {YDL_OPTS["cookiefile"]}')

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
    """수동 자막 우선, 없으면 자동생성. (segments, lang). 없으면 ([], 'none')."""
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

def is_botblock(msg):
    m = (msg or '').lower()
    return 'not a bot' in m or 'sign in to confirm' in m

def is_ratelimit(msg):
    m = (msg or '').lower()
    return '429' in m or 'too many requests' in m or 'rate-limit' in m

def text_in_window(segments, w_start, w_end):
    return ' '.join(c['text'] for c in segments
                    if c['end'] >= w_start and c['start'] <= w_end)

def collect_videos():
    seen, items = set(), []
    for name in FOLDERS:
        path = _find_csv(name)
        if not path:
            continue
        with open(path, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                vid = row['video_id']
                if vid not in seen:
                    seen.add(vid)
                    items.append((vid, row['video_url']))
    return items

def _is_done(vid):
    """transcripts/{vid}.json 이 '제대로 된' 결과면 True. error면 다시 받아야 하니 False."""
    p = os.path.join(TDIR, f'{vid}.json')
    if not os.path.exists(p):
        return False
    try:
        d = json.load(open(p, encoding='utf-8'))
        return d.get('lang') != 'error'      # 'none'/'ko'/'ko(auto)' 는 완료로 인정
    except Exception:
        return False

def fetch_round(videos):
    """한 라운드. (받은수, blocked) 반환. 실패는 파일 안 남김."""
    consec_bad = got = 0
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        for i, (vid, url) in enumerate(videos, 1):
            if _is_done(vid):
                continue
            out = os.path.join(TDIR, f'{vid}.json')
            try:
                info = ydl.extract_info(url, download=False)
                seg, lang = get_transcript(info)
            except Exception as e:
                msg = str(e)
                if is_botblock(msg) or is_ratelimit(msg):
                    consec_bad += 1
                    print(f'  [{i}] 차단/429 {consec_bad}회', flush=True)
                    if consec_bad >= BOT_STOP:
                        print('차단 지속 → 라운드 중단 (쿨다운)', flush=True)
                        return got, True
                    time.sleep(5)
                    continue
                print(f'  [{i}] 오류(스킵, 나중 재시도): {msg[:60]}', flush=True)
                time.sleep(2)
                continue
            consec_bad = 0
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({'lang': lang, 'segments': seg}, f, ensure_ascii=False, indent=2)
            got += 1
            print(f'  [{i}] {vid}  {lang}  {len(seg)}seg', flush=True)
            time.sleep(SLEEP)
    return got, False

def enrich_csvs():
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
    for name in FOLDERS:
        src = _find_csv(name)
        if not src:
            continue
        rows = list(csv.DictReader(open(src, encoding='utf-8-sig')))
        for r in rows:
            seg, lang = load(r['video_id'])
            s = int(r['start_time_sec']); e = int(r.get('end_time_sec') or s)
            r['transcript_text'] = text_in_window(seg, max(0, s - PAD), e + PAD)
            r['transcript_lang'] = lang
        if not rows:
            continue
        dst = src.replace('.csv', '_text.csv')
        with open(dst, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f'CSV 확장 저장: {dst}')

def main():
    os.makedirs(TDIR, exist_ok=True)
    videos = collect_videos()
    print(f'자막 대상 영상: {len(videos)}개\n')
    for rnd in range(1, MAX_ROUNDS + 1):
        print(f'===== 라운드 {rnd} =====', flush=True)
        got, blocked = fetch_round(videos)
        left = sum(1 for v, _ in videos if not _is_done(v))
        print(f'라운드 {rnd}: +{got}, 남음 {left}', flush=True)
        if left == 0:
            break
        wait = random.randint(*COOLDOWN) if blocked else random.randint(120, 300)
        print(f'{wait // 60}분 대기 후 재개...\n', flush=True)
        time.sleep(wait)
    print('\n자막 수집 종료 → CSV 확장본 생성', flush=True)
    enrich_csvs()

if __name__ == '__main__':
    main()
