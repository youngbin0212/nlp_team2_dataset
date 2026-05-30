"""크로스 영상 검증: 다른 경기 영상의 게임화면이 DMiGQavPyCc 레퍼런스 미니맵에
높게 매칭되는지 확인. (협곡 지형 동일 가정 검증)"""
import yt_dlp, subprocess, os, cv2

YDL = {'quiet': True, 'no_warnings': True,
       'format': 'bestvideo[ext=mp4]/bestvideo/best',
       'remote_components': ['ejs:github']}

# (video_id, 초) — 이전 로그에서 게임화면으로 확인된 지점들
TESTS = [
    ('oKX2JnXumc0', 561), ('oKX2JnXumc0', 821),
    ('3d75R9puc6E', 391), ('3d75R9puc6E', 133),
    ('UmsYeX-BA1E', 311), ('mwqs9jvSjXY', 183),
]

def br_region(img, fx0=0.83, fy0=0.74):
    h, w = img.shape[:2]
    return img[int(h*fy0):, int(w*fx0):]

ref = cv2.cvtColor(br_region(cv2.imread('output/DMiGQavPyCc_3.png')), cv2.COLOR_BGR2GRAY)

def score(path):
    img = cv2.imread(path); h, w = img.shape[:2]
    search = cv2.cvtColor(img[int(h*0.70):, int(w*0.78):], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(search, ref, cv2.TM_CCOEFF_NORMED).max())

os.makedirs('crosstest', exist_ok=True)
for vid, ts in TESTS:
    url = f'https://www.youtube.com/watch?v={vid}'
    with yt_dlp.YoutubeDL(YDL) as ydl:
        info = ydl.extract_info(url, download=False)
    out = f'crosstest/{vid}_{ts}.png'
    subprocess.run(['ffmpeg', '-ss', str(ts), '-i', info['url'],
                    '-frames:v', '1', out, '-y'], capture_output=True)
    print(f'{score(out):6.3f}  {out}  ({info.get("duration")}s)')
