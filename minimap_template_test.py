"""미니맵 템플릿 매칭 테스트.
소환사 협곡 지형은 모든 게임화면에서 동일 → 한 게임프레임의 우하단(미니맵)을
레퍼런스로 두고 matchTemplate. 게임화면이면 high, 선수컷/수상화면이면 low.
정답: _1(선수의자)·_5(POM) = 비게임 / _2,_3,_4 = 게임
"""
import cv2, glob, numpy as np

def br_region(img, fx0=0.83, fy0=0.74):
    h, w = img.shape[:2]
    return img[int(h*fy0):, int(w*fx0):]

# 레퍼런스: 게임화면으로 확인된 _3 의 미니맵 영역(그레이스케일)
ref_img = cv2.imread('output/DMiGQavPyCc_3.png')
ref = cv2.cvtColor(br_region(ref_img), cv2.COLOR_BGR2GRAY)

def match_score(p):
    img = cv2.imread(p)
    h, w = img.shape[:2]
    # 검색영역은 레퍼런스보다 약간 넓게 (우하단 28%)
    search = cv2.cvtColor(img[int(h*0.70):, int(w*0.78):], cv2.COLOR_BGR2GRAY)
    if search.shape[0] < ref.shape[0] or search.shape[1] < ref.shape[1]:
        return -1
    res = cv2.matchTemplate(search, ref, cv2.TM_CCOEFF_NORMED)
    return float(res.max())

print(f'{"match":>6}  file')
for p in sorted(glob.glob('output/*.png') + glob.glob('output_noheatmap/*.png')):
    print(f'{match_score(p):6.3f}  {p}')
