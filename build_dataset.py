"""LoL 하이라이트 이미지 데이터셋 빌더 (이미지 전용).

- heatmap 있는 영상(has_heatmap.jsonl): most-replayed 상위 → output/has_heatmap/
- heatmap 없는 영상(no_heatmap.jsonl): 균등분할(앞 10초 skip) → output/no_heatmap/
- 두 방식 모두 미니맵 매칭(minimap_filter)으로 '게임화면'만 영상당 5장.
- CSV는 각 폴더에 highlights.csv (video_id 기준 resume/이어하기).
- 자막은 별도(fetch_transcripts.py).

실행:
    $env:PATH = "C:\\Users\\kimyb\\.deno\\bin;$env:PATH"
    python build_dataset.py            # 1회 실행
    python run_until_done.py           # 봇차단 자동 대응 반복 실행
"""
import yt_dlp
import subprocess
import os
import csv
import time

# 추출 옵션: deno + ejs:github(원격 솔버), progressive best(1920x1080 캡처).
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'format': 'best[ext=mp4]/best',
    'remote_components': ['ejs:github'],
    'sleep_interval_requests': 2,
}
# 봇 차단 우회: cookies.txt 또는 *cookies*.txt 중 '가장 최근' 파일 자동 사용.
import glob as _glob
_ck = [c for c in set(_glob.glob('cookies.txt') + _glob.glob('*cookies*.txt'))
       if os.path.exists(c)]
if _ck:
    YDL_OPTS['cookiefile'] = max(_ck, key=os.path.getmtime)

FIELDNAMES = [
    'video_id', 'video_title', 'video_url', 'duration_sec', 'rank', 'source',
    'score', 'minimap_score', 'start_time_sec', 'end_time_sec',
    'timestamp', 'timestamp_end', 'image_file',
]

BOT_STOP = 8   # 연속 봇차단 이만큼이면 라운드 중단(쿨다운 필요)

def format_time(seconds):
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'

def _is_botblock(msg):
    m = (msg or '').lower()
    return 'not a bot' in m or 'sign in to confirm' in m

def select_heatmap(info, n, min_gap):
    """most-replayed에서 value 상위 + min_gap 간격으로 최대 n개 후보. 없으면 None."""
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

_SLOT_FRACS = [0.5, 0.35, 0.65, 0.2, 0.8]

def uniform_slots(info, top_n, intro_skip=10):
    """앞 intro_skip초 건너뛰고 전 구간 top_n등분. 구간마다 시도 후보 리스트."""
    duration = info.get('duration') or 0
    start_bound = intro_skip if duration > intro_skip else 0
    span = max(0, duration - start_bound)
    slots = []
    for i in range(top_n):
        a = start_bound + span * i / top_n
        b = start_bound + span * (i + 1) / top_n
        slots.append([{'start': a + (b - a) * fr, 'end': a + (b - a) * fr, 'score': None}
                      for fr in _SLOT_FRACS])
    return slots

def _capture(video_url, ts, out_path, tries=3):
    """ts 1프레임을 png로 캡처. 빈 프레임이면 재시도. -reconnect로 끊김 복구."""
    for _ in range(tries):
        subprocess.run([
            'ffmpeg', '-reconnect', '1', '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5', '-ss', str(ts), '-i', video_url,
            '-frames:v', '1', out_path, '-y'
        ], capture_output=True)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return True
        time.sleep(2)
    return False

def process_video(url, output_dir, method='heatmap', top_n=5, min_gap=60,
                  filter_game=True, thresh=0.50):
    """영상 1개 처리. 게임화면(미니맵)만 골라 최대 top_n장. 행 리스트 반환."""
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

    if filter_game:
        import minimap_filter

    os.makedirs(output_dir, exist_ok=True)
    video_url = info['url']
    tmp = os.path.join(output_dir, f'_tmp_{video_id}.png')

    def check(ts):
        if not _capture(video_url, ts, tmp):
            return None
        return minimap_filter.minimap_score(tmp) if filter_game else 1.0

    chosen = []
    if method == 'heatmap':
        for c in cands:
            if len(chosen) >= top_n:
                break
            gp = check(c['start'])
            if gp is not None and gp >= thresh:
                final = os.path.join(output_dir, f'{video_id}_{len(chosen)+1}.png')
                os.replace(tmp, final)
                chosen.append((c, gp, final))
    else:
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
        start, end = c['start'], c['end']
        fname = os.path.basename(final)
        print(f'  캡처: [{format_time(start)}] {fname}  minimap={gp:.2f}')
        rows.append({
            'video_id': video_id, 'video_title': title, 'video_url': url,
            'duration_sec': int(duration), 'rank': i + 1, 'source': method,
            'score': round(c['score'], 4) if c['score'] is not None else '',
            'minimap_score': round(gp, 3),
            'start_time_sec': int(start), 'end_time_sec': int(end),
            'timestamp': format_time(start), 'timestamp_end': format_time(end),
            'image_file': fname,
        })
    if len(chosen) < top_n:
        print(f'  [주의] {video_id}: 게임화면 {len(chosen)}/{top_n}장만 확보')
    return rows

def load_items(list_file):
    """jsonl(한 줄=JSON, video_id/url) 또는 txt(한 줄=URL)에서 {video_id, url} 목록."""
    import json
    items = []
    with open(list_file, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if list_file.endswith('.jsonl'):
                obj = json.loads(ln)
                vid = obj.get('video_id')
                url = obj.get('url') or f'https://www.youtube.com/watch?v={vid}'
                items.append({'video_id': vid, 'url': url})
            else:
                items.append({'video_id': ln.rsplit('=', 1)[-1], 'url': ln})
    return items

def _done_video_ids(csv_path):
    """기존 CSV에 기록된 video_id 집합 (이어하기용)."""
    done = set()
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                if row.get('video_id'):
                    done.add(row['video_id'])
    return done

def build_dataset(list_file, output_dir, method='heatmap', top_n=5, min_gap=60,
                  limit=None, filter_game=True, thresh=0.50, resume=True):
    """1회 실행. 봇 차단이 연속 BOT_STOP회면 중단하고 blocked=True 반환.
    반환: {processed, images, remaining, blocked}"""
    os.makedirs(output_dir, exist_ok=True)
    items = load_items(list_file)
    if limit:
        items = items[:limit]

    csv_path = os.path.join(output_dir, 'highlights.csv')
    done = _done_video_ids(csv_path) if resume else set()

    new_file = not os.path.exists(csv_path)
    f = open(csv_path, 'a', newline='', encoding='utf-8-sig')
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    if new_file:
        writer.writeheader()
        f.flush()

    todo = sum(1 for it in items if it['video_id'] not in done)
    print(f'[{method}] {list_file} → {output_dir} : 총 {len(items)} (완료 {len(done)}, 남음 {todo})')

    processed = n_img = consec_bot = 0
    blocked = False
    for idx, it in enumerate(items, 1):
        if it['video_id'] in done:
            continue
        print(f'[{idx}/{len(items)}] {it["url"]}')
        try:
            rows = process_video(it['url'], output_dir, method=method,
                                 top_n=top_n, min_gap=min_gap,
                                 filter_game=filter_game, thresh=thresh)
            for r in rows:
                writer.writerow(r)
            f.flush()
            done.add(it['video_id'])
            processed += 1
            n_img += len(rows)
            consec_bot = 0
        except Exception as e:
            if _is_botblock(str(e)):
                consec_bot += 1
                print(f'  [봇차단] {consec_bot}회 연속')
                if consec_bot >= BOT_STOP:
                    print('봇 차단 지속 → 이번 라운드 중단 (쿨다운 필요)')
                    blocked = True
                    break
            else:
                print(f'  [오류] 처리 실패: {e}')
        print()

    f.close()
    remaining = sum(1 for it in items if it['video_id'] not in done)
    print(f'라운드 종료: 신규 {processed}, 이미지 {n_img}, 남음 {remaining}'
          + (' [봇차단 중단]' if blocked else ''))
    return {'processed': processed, 'images': n_img,
            'remaining': remaining, 'blocked': blocked}

if __name__ == '__main__':
    build_dataset('has_heatmap.jsonl', 'output/has_heatmap', method='heatmap')
    build_dataset('no_heatmap.jsonl', 'output/no_heatmap', method='uniform')
