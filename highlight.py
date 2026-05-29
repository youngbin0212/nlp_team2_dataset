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

def capture_most_replayed(url, top_n=5, min_gap=60, output_dir='captures'):
    os.makedirs(output_dir, exist_ok=True)

    # 1. 메타데이터 + 스트림 URL 추출
    # 프레임 캡처는 음성이 필요 없으므로, 음성 없는 최고화질 영상 스트림을 우선 선택
    # (best=영상+음성 합본은 유튜브에서 보통 720p 이하로 제한됨)
    ydl_opts = {
        'quiet': True,
        'format': 'bestvideo[ext=mp4]/bestvideo/best',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    heatmap = info.get('heatmap')
    if not heatmap:
        print('이 영상은 heatmap 데이터가 없습니다 (조회수가 적거나 비공개)')
        return

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

    # 3. 각 시점에서 프레임 추출 + 결과 기록
    video_url = info['url']
    rows = []
    for i, h in enumerate(top):
        ts = h['start_time']  # 초 단위
        time_str = format_time(ts)
        out = f'{output_dir}/top{i+1}_{int(ts)}s_score{h["value"]:.2f}.jpg'
        subprocess.run([
            'ffmpeg', '-ss', str(ts), '-i', video_url,
            '-frames:v', '1', '-q:v', '2', out, '-y'
        ], capture_output=True)
        print(f'캡처 완료: [{time_str}] {out}')
        rows.append({
            'rank': i + 1,
            'timestamp': time_str,         # HH:MM:SS 형식 시간대
            'start_time_sec': int(ts),     # 초 단위 시간대
            'score': round(h['value'], 4), # 재생 강도
            'image_file': out,             # 캡처 이미지 경로
        })

    # 4. CSV로 정리 저장
    csv_path = f'{output_dir}/highlights.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(
            f, fieldnames=['rank', 'timestamp', 'start_time_sec', 'score', 'image_file']
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f'\nCSV 저장 완료: {csv_path} (총 {len(rows)}개)')

capture_most_replayed('https://www.youtube.com/watch?v=UAUErgpdksM', top_n=5, min_gap=60)
