"""봇 차단을 피하며 데이터셋을 끝까지 채우는 자동 반복 실행기.

동작:
 - has_heatmap, no_heatmap 빌드를 resume로 실행
 - 봇 차단이 연속 감지되면 그 라운드를 '즉시 중단'하고 (계속 두드리지 않음)
 - 길게(40~80분, 랜덤) 쉰 뒤 다음 라운드 재개  ← 사람처럼 띄엄띄엄
 - 남은 영상이 0이 되면 종료

실행:
    $env:PATH = "C:\\Users\\kimyb\\.deno\\bin;$env:PATH"
    python run_until_done.py
"""
import time
import random
import build_dataset as b

JOBS = [
    ('has_heatmap.jsonl', 'output/has_heatmap', 'heatmap'),
    ('no_heatmap.jsonl', 'output/no_heatmap', 'uniform'),
]
MAX_ROUNDS = 60

def remaining_total():
    tot = 0
    for lf, od, _ in JOBS:
        done = b._done_video_ids(f'{od}/highlights.csv')
        items = b.load_items(lf)
        tot += sum(1 for it in items if it['video_id'] not in done)
    return tot

def main():
    for rnd in range(1, MAX_ROUNDS + 1):
        print(f'\n===== 라운드 {rnd} =====', flush=True)
        blocked = False
        for lf, od, m in JOBS:
            r = b.build_dataset(lf, od, method=m)
            if r['blocked']:
                blocked = True
                break          # 차단되면 다음 작업으로 넘어가지 말고 쿨다운
        left = remaining_total()
        print(f'\n>>> 현재 남은 영상: {left}개', flush=True)
        if left == 0:
            print('\n========== 전체 완료! ==========', flush=True)
            return
        # 차단이면 길게(40~80분), 아니면 짧게(2~5분) 쉬고 재개
        wait = random.randint(2400, 4800) if blocked else random.randint(120, 300)
        print(f'{wait // 60}분 대기 후 재개...', flush=True)
        time.sleep(wait)
    print('\n최대 라운드 도달. 남은 게 있으면 다시 실행하세요.', flush=True)

if __name__ == '__main__':
    main()
