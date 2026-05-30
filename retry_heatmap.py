"""rate-limit으로 실패했던 영상만 재시도해 heatmap 유무를 채운다.
- 요청 간 sleep으로 재차단 방지, 차단 감지 시 백오프 후 재시도.
- 끝나면 heatmap_scan.jsonl 갱신 + has_heatmap.jsonl / no_heatmap.jsonl 재생성.
"""
import yt_dlp, json, time

INPUT = 'lol_url_successed.jsonl'
SCAN = 'heatmap_scan.jsonl'
HAVE_OUT = 'has_heatmap.jsonl'
NONE_OUT = 'no_heatmap.jsonl'

def load_jsonl(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]

def is_ratelimit(msg):
    return 'rate-limit' in (msg or '').lower() or 'try again later' in (msg or '').lower()

def regenerate(scan_by_id, orig_by_id):
    """scan 결과로 3개 파일 재작성."""
    with open(SCAN, 'w', encoding='utf-8') as sf, \
         open(HAVE_OUT, 'w', encoding='utf-8') as hf, \
         open(NONE_OUT, 'w', encoding='utf-8') as nf:
        for vid, rec in scan_by_id.items():
            sf.write(json.dumps(rec, ensure_ascii=False) + '\n')
            orig = orig_by_id.get(vid, {'video_id': vid, 'url': rec.get('url')})
            if rec.get('n_heatmap'):            # >0
                hf.write(json.dumps(orig, ensure_ascii=False) + '\n')
            else:                                # 0 또는 여전히 error
                nf.write(json.dumps(orig, ensure_ascii=False) + '\n')

def main():
    orig_by_id = {r['video_id']: r for r in load_jsonl(INPUT)}
    scan_by_id = {r['video_id']: r for r in load_jsonl(SCAN)}

    todo = [vid for vid, r in scan_by_id.items() if r.get('error')]
    total = len(todo)
    print(f'재시도 대상: {total}개', flush=True)

    opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'remote_components': ['ejs:github'],
        'sleep_interval_requests': 2,   # 요청 간 2초
    }

    fixed = still = 0
    with yt_dlp.YoutubeDL(opts) as ydl:
        for i, vid in enumerate(todo, 1):
            rec = scan_by_id[vid]
            url = rec['url']
            for attempt in (1, 2):
                try:
                    info = ydl.extract_info(url, download=False)
                    hm = info.get('heatmap')
                    rec['n_heatmap'] = len(hm) if hm else 0
                    rec['duration'] = info.get('duration')
                    rec['error'] = None
                    fixed += 1
                    break
                except Exception as e:
                    msg = str(e)
                    rec['error'] = msg[:200]
                    if is_ratelimit(msg) and attempt == 1:
                        print(f'  [{i}] rate-limit 감지 → 90초 대기 후 재시도', flush=True)
                        time.sleep(90)
                        continue
                    still += 1
                    break

            if i % 20 == 0 or i == total:
                print(f'[{i}/{total}] 해결={fixed} 여전히실패={still}', flush=True)
                regenerate(scan_by_id, orig_by_id)   # 중간 저장

    regenerate(scan_by_id, orig_by_id)
    have = sum(1 for r in scan_by_id.values() if r.get('n_heatmap'))
    none = sum(1 for r in scan_by_id.values() if r.get('n_heatmap') == 0)
    err = sum(1 for r in scan_by_id.values() if r.get('error'))
    print(f'완료: 재시도 {total} | 해결 {fixed} | 여전히실패 {still}', flush=True)
    print(f'전체 → heatmap있음 {have} | 없음 {none} | 미해결오류 {err}', flush=True)

if __name__ == '__main__':
    main()
