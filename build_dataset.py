import yt_dlp
import subprocess
import os
import csv
import json
import urllib.request

def format_time(seconds):
    """초 단위를 HH:MM:SS 형식 문자열로 변환"""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'

# CSV 컬럼 정의 (한 줄 = 하이라이트 1개 = VLM 입력 1개)
FIELDNAMES = [
    'video_id',         # 유튜브 영상 ID  ← 자막 파트와 join 하는 키
    'video_title',      # 영상 제목
    'video_url',        # 영상 URL
    'duration_sec',     # 영상 전체 길이(초)
    'rank',             # 해당 영상 내 하이라이트 순위 (1~top_n)
    'score',            # 재생 강도(value)
    'start_time_sec',   # 하이라이트 구간 시작(초)
    'end_time_sec',     # 하이라이트 구간 끝(초)
    'timestamp',        # 시작 시각 (HH:MM:SS)
    'timestamp_end',    # 끝 시각 (HH:MM:SS)
    'window_start_sec', # 해설을 긁어온 맥락 윈도우 시작(초)
    'window_end_sec',   # 해설을 긁어온 맥락 윈도우 끝(초)
    'transcript_text',  # 그 윈도우에 겹치는 해설(자막) 텍스트  ← VLM 맥락 입력
    'transcript_lang',  # 자막 언어/출처 (예: ko, ko(auto), none)
    'image_file',       # 캡처 이미지 경로 (captures 기준 상대경로)
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
            # json3 포맷 URL 우선 선택 (타임코드 파싱이 가장 깔끔)
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

def process_video(url, output_dir, top_n=5, min_gap=60, context_pad=15):
    """영상 1개를 처리해서 하이라이트 행 리스트를 반환. 실패하면 빈 리스트."""
    # 1. 메타데이터 + 스트림 URL + 자막 정보 추출
    # 프레임 캡처는 음성이 필요 없으므로, 음성 없는 최고화질 영상 스트림을 우선 선택
    ydl_opts = {
        'quiet': True,
        'format': 'bestvideo[ext=mp4]/bestvideo/best',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info['id']
    title = info.get('title', '')
    duration = info.get('duration', 0)

    heatmap = info.get('heatmap')
    if not heatmap:
        print(f'  [건너뜀] heatmap 데이터 없음: {video_id}')
        return []

    # 2. value 높은 순 정렬 후, 이미 뽑은 하이라이트와 min_gap(초) 이상
    #    떨어진 것만 채택 (서로 다른 장면 보장)
    candidates = sorted(heatmap, key=lambda x: x['value'], reverse=True)
    top = []
    for h in candidates:
        ts = h['start_time']
        if all(abs(ts - p['start_time']) >= min_gap for p in top):
            top.append(h)
        if len(top) == top_n:
            break

    # 3. 자막(해설) 가져오기 + 영상별 전체 자막 저장 (RAG/context용)
    transcript, lang_tag = fetch_transcript(info, langs=('ko',))
    if transcript:
        tdir = os.path.join(output_dir, 'transcripts')
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, f'{video_id}.json'), 'w', encoding='utf-8') as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
    else:
        print(f'  [자막 없음] {video_id} ({lang_tag})')

    # 4. 영상별 하위 폴더 생성 + 각 하이라이트 프레임 추출 + 해설 매칭
    video_dir = os.path.join(output_dir, video_id)
    os.makedirs(video_dir, exist_ok=True)

    video_url = info['url']
    rows = []
    for i, h in enumerate(top):
        rank = i + 1
        start = h['start_time']
        end = h.get('end_time', start)
        # 해설 맥락 윈도우: 구간 앞뒤로 context_pad초 여유 (영상 길이 안으로 clamp)
        w_start = max(0, start - context_pad)
        w_end = min(duration, end + context_pad) if duration else end + context_pad

        # 이미지 이름: 영상ID_top순위_초.jpg  → 파일만 봐도 식별 가능
        fname = f'{video_id}_top{rank}_{int(start)}s.jpg'
        out = os.path.join(video_dir, fname)
        subprocess.run([
            'ffmpeg', '-ss', str(start), '-i', video_url,
            '-frames:v', '1', '-q:v', '2', out, '-y'
        ], capture_output=True)

        snippet = text_in_window(transcript, w_start, w_end)
        print(f'  캡처: [{format_time(start)}] {fname}  해설 {len(snippet)}자')
        rows.append({
            'video_id': video_id,
            'video_title': title,
            'video_url': url,
            'duration_sec': int(duration),
            'rank': rank,
            'score': round(h['value'], 4),
            'start_time_sec': int(start),
            'end_time_sec': int(end),
            'timestamp': format_time(start),
            'timestamp_end': format_time(end),
            'window_start_sec': int(w_start),
            'window_end_sec': int(w_end),
            'transcript_text': snippet,
            'transcript_lang': lang_tag,
            'image_file': os.path.join(video_id, fname).replace('\\', '/'),
        })
    return rows

def build_dataset(list_file='list.txt', output_dir='captures',
                  top_n=5, min_gap=60, context_pad=15):
    os.makedirs(output_dir, exist_ok=True)

    # list.txt에서 URL 읽기 (빈 줄 / # 주석 무시)
    with open(list_file, encoding='utf-8') as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith('#')]

    print(f'총 {len(urls)}개 영상 처리 시작\n')

    all_rows = []
    for idx, url in enumerate(urls, 1):
        print(f'[{idx}/{len(urls)}] {url}')
        try:
            rows = process_video(url, output_dir, top_n=top_n,
                                  min_gap=min_gap, context_pad=context_pad)
            all_rows.extend(rows)
        except Exception as e:
            # 한 영상이 실패해도 전체 배치는 계속 진행
            print(f'  [오류] 처리 실패: {e}')
        print()

    # 모든 영상 결과를 하나의 통합 CSV로 저장
    csv_path = os.path.join(output_dir, 'highlights.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f'완료: 영상 {len(urls)}개, 하이라이트 {len(all_rows)}개')
    print(f'CSV 저장: {csv_path}')
    print(f'전체 자막: {os.path.join(output_dir, "transcripts")}/{{video_id}}.json')

if __name__ == '__main__':
    build_dataset('list.txt', top_n=5, min_gap=60, context_pad=15)
