"""전체 영상을 스캔해 heatmap(most-replayed) 유무를 분류한다.
deno + ejs:github(원격 솔버)로 정상 추출 후, heatmap 포인트 개수를 기록.
결과:
    heatmap_scan.jsonl : 모든 영상 {video_id, url, title, n_heatmap, duration, error}
    has_heatmap.jsonl  : heatmap 있는 영상만 (원본 레코드) -> 데이터셋 입력용
    no_heatmap.jsonl   : heatmap 없는 영상만 (원본 레코드) -> 팀원에게 교체 요청용
진행상황은 stdout으로 출력(백그라운드 로그로 확인).
"""
import yt_dlp
import json

INPUT = 'lol_url_successed.jsonl'
SCAN_OUT = 'heatmap_scan.jsonl'
HAVE_OUT = 'has_heatmap.jsonl'
NONE_OUT = 'no_heatmap.jsonl'

def load_items(path):
    items = []
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                items.append(json.loads(ln))
    return items

def main():
    items = load_items(INPUT)
    total = len(items)
    print(f'스캔 시작: {total}개', flush=True)

    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'remote_components': ['ejs:github'],
    }

    have = none = err = 0
    scan_f = open(SCAN_OUT, 'w', encoding='utf-8')
    have_f = open(HAVE_OUT, 'w', encoding='utf-8')
    none_f = open(NONE_OUT, 'w', encoding='utf-8')

    with yt_dlp.YoutubeDL(opts) as ydl:
        for i, it in enumerate(items, 1):
            vid = it.get('video_id')
            url = it.get('url') or f'https://www.youtube.com/watch?v={vid}'
            rec = {'video_id': vid, 'url': url, 'title': it.get('title'),
                   'n_heatmap': None, 'duration': None, 'error': None}
            try:
                info = ydl.extract_info(url, download=False)
                hm = info.get('heatmap')
                n = len(hm) if hm else 0
                rec['n_heatmap'] = n
                rec['duration'] = info.get('duration')
                if n > 0:
                    have += 1
                    have_f.write(json.dumps(it, ensure_ascii=False) + '\n')
                    have_f.flush()
                else:
                    none += 1
                    none_f.write(json.dumps(it, ensure_ascii=False) + '\n')
                    none_f.flush()
            except Exception as e:
                # 추출 자체 실패도 "없음"이 아니라 별도 오류로 기록 (재시도 대상)
                err += 1
                rec['error'] = str(e)[:200]
                none_f.write(json.dumps(it, ensure_ascii=False) + '\n')
                none_f.flush()
            scan_f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            scan_f.flush()

            if i % 20 == 0 or i == total:
                print(f'[{i}/{total}] heatmap있음={have} 없음={none} 오류={err}', flush=True)

    scan_f.close()
    have_f.close()
    none_f.close()
    print(f'완료: 총 {total} | heatmap있음 {have} | 없음 {none} | 오류 {err}', flush=True)
    print(f'-> {SCAN_OUT} / {HAVE_OUT} / {NONE_OUT}', flush=True)

if __name__ == '__main__':
    main()
