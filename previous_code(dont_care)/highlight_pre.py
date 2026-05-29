import yt_dlp
import subprocess
import os

def capture_most_replayed(url, top_n=5, output_dir='captures'):
    os.makedirs(output_dir, exist_ok=True)

    # 1. 메타데이터 + 스트림 URL 추출
    ydl_opts = {'quiet': True, 'format': 'best[ext=mp4]/best'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    heatmap = info.get('heatmap')
    if not heatmap:
        print('이 영상은 heatmap 데이터가 없습니다 (조회수가 적거나 비공개)')
        return

    # 2. value(재생 강도) 높은 순으로 정렬
    top = sorted(heatmap, key=lambda x: x['value'], reverse=True)[:top_n]

    # 3. 각 시점에서 프레임 추출
    video_url = info['url']
    for i, h in enumerate(top):
        ts = h['start_time']  # 초 단위
        out = f'{output_dir}/top{i+1}_{int(ts)}s_score{h["value"]:.2f}.jpg'
        subprocess.run([
            'ffmpeg', '-ss', str(ts), '-i', video_url,
            '-frames:v', '1', '-q:v', '2', out, '-y'
        ], capture_output=True)
        print(f'캡처 완료: {out}')

capture_most_replayed('https://www.youtube.com/watch?v=VIDEO_ID', top_n=5)