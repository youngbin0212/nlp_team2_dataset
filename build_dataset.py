import yt_dlp
import subprocess
import os
import csv
import json
import urllib.request

# 공통 추출 옵션: deno + ejs:github(원격 솔버)로 정상 추출, 요청 간 텀으로 차단 방지
# 프레임 캡처는 음성이 필요 없으므로 음성 없는 최고화질 영상 스트림을 우선 선택
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'format': 'bestvideo[ext=mp4]/bestvideo/best',
    'remote_components': ['ejs:github'],
    'sleep_interval_requests': 2,
}

def format_time(seconds):
    """초 단위를 HH:MM:SS 형식 문자열로 변환"""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'

# CSV 컬럼 정의 (한 줄 = 이미지 1개 = VLM 입력 1개)
FIELDNAMES = [
    'video_id',         # 유튜브 영상 ID  ← 자막 파트와 join 하는 키
    'video_title',      # 영상 제목
    'video_url',        # 영상 URL
    'duration_sec',     # 영상 전체 길이(초)
    'rank',             # 해당 영상 내 추출 순위 (1~top_n)
    'source',           # 추출 방식: heatmap(most-replayed) / uniform(균등분할)
    'score',            # 재생 강도(value). uniform이면 빈 값
    'game_prob',        # CLIP 게임화면 확률(0~1). 필터 통과 점수
    'start_time_sec',   # 추출 지점 시작(초)
    'end_time_sec',     # 추출 지점 끝(초)
    'timestamp',        # 시작 시각 (HH:MM:SS)
    'timestamp_end',    # 끝 시각 (HH:MM:SS)
    'window_start_sec', # 해설을 긁어온 맥락 윈도우 시작(초)
    'window_end_sec',   # 해설을 긁어온 맥락 윈도우 끝(초)
    'transcript_text',  # 그 윈도우에 겹치는 해설(자막) 텍스트  ← VLM 맥락 입력
    'transcript_lang',  # 자막 언어/출처 (예: ko, ko(auto), none)
    'image_file',       # 캡처 이미지 파일명
]

def parse_json3(raw_bytes):
    """유튜브 json3 자막을 [{start, end, text}, ...] 리스트로 파싱"""
    data = json.loads(raw_bytes)
    out = []
    for ev in data.get('events', []):
        if 'segs' not in ev:
            continue
        text = ''.join(seg.get('utf8', '') for seg in ev['segs']).strip()
        if not text:
            continue
        start = ev.get('tStartMs', 0) / 1000.0
        dur = ev.get('dDurationMs', 0) / 1000.0
        out.append({'start': start, 'end': start + dur, 'text': text})
    return out

def fetch_transcript(info, langs=('ko',)):
    """수동 자막 우선, 없으면 자동생성 자막을 가져온다.
    반환: (transcript 리스트, 언어태그 문자열)"""
    sources = [('subtitles', ''), ('automatic_captions', '(auto)')]
    for key, suffix in sources:
        subs = info.get(key) or {}
        for lang in langs:
            if lang not in subs:
                continue
            url = next((f['url'] for f in subs[lang] if f.get('ext') == 'json3'), None)
            if not url:
                continue
            try:
                raw = urllib.request.urlopen(url, timeout=30).read()
                return parse_json3(raw), f'{lang}{suffix}'
            except Exception as e:
                print(f'  [자막 경고] {lang}{suffix} 가져오기 실패: {e}')
    return [], 'none'

def text_in_window(transcript, w_start, w_end):
    """[w_start, w_end] 구간과 겹치는 자막 텍스트를 한 줄로 합쳐 반환"""
    parts = [c['text'] for c in transcript
             if c['end'] >= w_start and c['start'] <= w_end]
    return ' '.join(parts)

def select_heatmap(info, n, min_gap):
    """most-replayed heatmap에서 value 상위 + min_gap 간격으로 최대 n개 후보 반환.
    heatmap이 없으면 None."""
    heatmap = info.get('heatmap')
    if not heatmap:
        return None
    candidates = sorted(heatmap, key=lambda x: x['value'], reverse=True)
    picks = []
    for h in candidates:
        ts = h['start_time']
        if all(abs(ts - p['start']) >= min_gap for p in picks):
            picks.append({'start': ts, 'end': h.get('end_time', ts), 'score': h['value']})
        if len(picks) >= n:
            break
    return picks

# 균등분할 슬롯 내 시도 순서(구간 내 위치 비율): 중앙 우선, 실패 시 좌우로
_SLOT_FRACS = [0.5, 0.35, 0.65, 0.2, 0.8]

def uniform_slots(info, top_n, intro_skip=10):
    """앞 intro_skip초 건너뛰고 전 구간을 top_n등분.
    각 구간(슬롯)마다 시도할 후보 지점 리스트를 반환 → 구간당 1장 채택용."""
    duration = info.get('duration') or 0
    start_bound = intro_skip if duration > intro_skip else 0
    span = max(0, duration - start_bound)
    slots = []
    for i in range(top_n):
        a = start_bound + span * i / top_n
        b = start_bound + span * (i + 1) / top_n
        cands = [{'start': a + (b - a) * fr, 'end': a + (b - a) * fr, 'score': None}
                 for fr in _SLOT_FRACS]
        slots.append(cands)
    return slots

def _capture(video_url, ts, out_path):
    """ts 지점 1프레임을 out_path(png)로 캡처. 성공 여부 반환."""
    subprocess.run([
        'ffmpeg', '-ss', str(ts), '-i', video_url,
        '-frames:v', '1', out_path, '-y'
    ], capture_output=True)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0

def process_video(url, output_dir, method='heatmap', top_n=5, min_gap=60,
                  context_pad=15, filter_game=True, thresh=0.5):
    """영상 1개 처리. 게임화면(CLIP)만 골라 최대 top_n장 확보. 행 리스트 반환."""
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info['id']
    title = info.get('title', '')
    duration = info.get('duration', 0)

    if method == 'heatmap':
        cands = select_heatmap(info, top_n * 4, min_gap)
        if cands is None:
            print(f'  [건너뜀] heatmap 없음: {video_id}')
            return []
    else:
        slots = uniform_slots(info, top_n)

    transcript, lang_tag = fetch_transcript(info, langs=('ko',))
    if transcript:
        tdir = os.path.join(output_dir, 'transcripts')
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, f'{video_id}.json'), 'w', encoding='utf-8') as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
    else:
        print(f'  [자막 없음] {video_id} ({lang_tag})')

    if filter_game:
        import clip_filter

    os.makedirs(output_dir, exist_ok=True)
    video_url = info['url']
    tmp = os.path.join(output_dir, f'_tmp_{video_id}.png')

    def check(ts):
        """ts 캡처 후 게임화면 확률 반환. 캡처 실패면 None."""
        if not _capture(video_url, ts, tmp):
            return None
        return clip_filter.game_prob(tmp) if filter_game else 1.0

    chosen = []   # (pick, game_prob, final_path)
    if method == 'heatmap':
        # value 높은 순으로 게임화면인 것만 top_n개 채움
        for c in cands:
            if len(chosen) >= top_n:
                break
            gp = check(c['start'])
            if gp is not None and gp >= thresh:
                final = os.path.join(output_dir, f'{video_id}_{len(chosen)+1}.png')
                os.replace(tmp, final)
                chosen.append((c, gp, final))
    else:
        # 구간(슬롯)마다 게임화면 나올 때까지 시도, 첫 통과분 채택
        for slot in slots:
            for c in slot:
                gp = check(c['start'])
                if gp is not None and gp >= thresh:
                    final = os.path.join(output_dir, f'{video_id}_{len(chosen)+1}.png')
                    os.replace(tmp, final)
                    chosen.append((c, gp, final))
                    break
    if os.path.exists(tmp):
        os.remove(tmp)

    rows = []
    for i, (c, gp, final) in enumerate(chosen):
        rank = i + 1
        start, end = c['start'], c['end']
        w_start = max(0, start - context_pad)
        w_end = min(duration, end + context_pad) if duration else end + context_pad
        fname = os.path.basename(final)
        snippet = text_in_window(transcript, w_start, w_end)
        print(f'  캡처: [{format_time(start)}] {fname}  game={gp:.2f}  해설 {len(snippet)}자')
        rows.append({
            'video_id': video_id,
            'video_title': title,
            'video_url': url,
            'duration_sec': int(duration),
            'rank': rank,
            'source': method,
            'score': round(c['score'], 4) if c['score'] is not None else '',
            'game_prob': round(gp, 3),
            'start_time_sec': int(start),
            'end_time_sec': int(end),
            'timestamp': format_time(start),
            'timestamp_end': format_time(end),
            'window_start_sec': int(w_start),
            'window_end_sec': int(w_end),
            'transcript_text': snippet,
            'transcript_lang': lang_tag,
            'image_file': fname,
        })
    if len(chosen) < top_n:
        print(f'  [주의] {video_id}: 게임화면 {len(chosen)}/{top_n}장만 확보')
    return rows

def load_urls(list_file):
    """입력 파일에서 URL 목록을 읽는다.
    - .jsonl: 한 줄 = JSON 객체, 'url'(없으면 video_id로 구성) 사용
    - 그 외(.txt): 한 줄 = URL (빈 줄 / # 주석 무시)
    """
    urls = []
    with open(list_file, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if list_file.endswith('.jsonl'):
                obj = json.loads(ln)
                urls.append(obj.get('url') or f'https://www.youtube.com/watch?v={obj["video_id"]}')
            else:
                urls.append(ln)
    return urls

def build_dataset(list_file, output_dir, method='heatmap',
                  top_n=5, min_gap=60, context_pad=15, limit=None,
                  filter_game=True, thresh=0.5):
    os.makedirs(output_dir, exist_ok=True)
    urls = load_urls(list_file)
    if limit:
        urls = urls[:limit]

    print(f'[{method}] {list_file} → {output_dir} : {len(urls)}개 처리 시작'
          f' (게임화면 필터={"ON" if filter_game else "OFF"})\n')

    all_rows = []
    for idx, url in enumerate(urls, 1):
        print(f'[{idx}/{len(urls)}] {url}')
        try:
            rows = process_video(url, output_dir, method=method,
                                  top_n=top_n, min_gap=min_gap, context_pad=context_pad,
                                  filter_game=filter_game, thresh=thresh)
            all_rows.extend(rows)
        except Exception as e:
            print(f'  [오류] 처리 실패: {e}')
        print()

    csv_path = os.path.join(output_dir, 'highlights.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f'완료: 영상 {len(urls)}개, 이미지 {len(all_rows)}개')
    print(f'CSV: {csv_path}')

if __name__ == '__main__':
    # 연습 실행: 각 방식 소수만
    build_dataset('has_heatmap.jsonl', 'output', method='heatmap', limit=3)
    build_dataset('no_heatmap.jsonl', 'output_noheatmap', method='uniform', limit=3)
