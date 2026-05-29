import yt_dlp
import subprocess
import os
import csv

def format_time(seconds):
    """초 단위를 HH:MM:SS 형식 문자열로 변환"""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'

# CSV 컬럼 정의 (한 줄 = 하이라이트 1개)
FIELDNAMES = [
    'video_id',        # 유튜브 영상 ID
    'video_title',     # 영상 제목
    'video_url',       # 영상 URL
    'duration_sec',    # 영상 전체 길이(초)
    'rank',            # 해당 영상 내 하이라이트 순위 (1~top_n)
    'timestamp',       # 하이라이트 시간대 (HH:MM:SS)
    'start_time_sec',  # 하이라이트 시간대 (초)
    'score',           # 재생 강도(value)
    'image_file',      # 캡처 이미지 경로 (captures 기준 상대경로)
]

def process_video(url, output_dir, top_n=5, min_gap=60):
    """영상 1개를 처리해서 하이라이트 행 리스트를 반환. 실패하면 빈 리스트."""
    # 1. 메타데이터 + 스트림 URL 추출
    # 프레임 캡처는 음성이 필요 없으므로, 음성 없는 최고화질 영상 스트림을 우선 선택
    # (best=영상+음성 합본은 유튜브에서 보통 720p 이하로 제한됨)
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

    # 2. value(재생 강도) 높은 순으로 정렬한 뒤,
    #    이미 뽑은 하이라이트와 min_gap(초) 이상 떨어진 것만 채택 (서로 다른 장면 보장)
    candidates = sorted(heatmap, key=lambda x: x['value'], reverse=True)
    top = []
    for h in candidates:
        ts = h['start_time']
        if all(abs(ts - p['start_time']) >= min_gap for p in top):
            top.append(h)
        if len(top) == top_n:
            break

    # 3. 영상별 하위 폴더 생성 + 각 시점에서 프레임 추출
    video_dir = os.path.join(output_dir, video_id)
    os.makedirs(video_dir, exist_ok=True)

    video_url = info['url']
    rows = []
    for i, h in enumerate(top):
        ts = h['start_time']  # 초 단위
        rank = i + 1
        # 이미지 이름: 영상ID_top순위_초.jpg  → 파일만 봐도 식별 가능
        fname = f'{video_id}_top{rank}_{int(ts)}s.jpg'
        out = os.path.join(video_dir, fname)
        subprocess.run([
            'ffmpeg', '-ss', str(ts), '-i', video_url,
            '-frames:v', '1', '-q:v', '2', out, '-y'
        ], capture_output=True)
        print(f'  캡처: [{format_time(ts)}] {fname}')
        rows.append({
            'video_id': video_id,
            'video_title': title,
            'video_url': url,
            'duration_sec': int(duration),
            'rank': rank,
            'timestamp': format_time(ts),
            'start_time_sec': int(ts),
            'score': round(h['value'], 4),
            'image_file': os.path.join(video_id, fname).replace('\\', '/'),
        })
    return rows

def build_dataset(list_file='list.txt', output_dir='captures', top_n=5, min_gap=60):
    os.makedirs(output_dir, exist_ok=True)

    # list.txt에서 URL 읽기 (빈 줄 / # 주석 무시)
    with open(list_file, encoding='utf-8') as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith('#')]

    print(f'총 {len(urls)}개 영상 처리 시작\n')

    all_rows = []
    for idx, url in enumerate(urls, 1):
        print(f'[{idx}/{len(urls)}] {url}')
        try:
            rows = process_video(url, output_dir, top_n=top_n, min_gap=min_gap)
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

if __name__ == '__main__':
    build_dataset('list.txt', top_n=5, min_gap=60)
