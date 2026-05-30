"""미니맵 템플릿 매칭으로 '게임화면' 판별 (cv2만 사용, GPU/torch 불필요).
소환사 협곡 지형은 모든 경기에서 동일 → 우하단 미니맵이 레퍼런스에 매칭되면 게임화면.
선수컷·수상화면·캐스터·관중은 미니맵이 없어 낮게 나온다.
검증(1080p, 14개 영상): 게임화면 0.58~0.76 / 비게임 <0.13 → 임계값 0.45 권장.
"""
import os
import cv2

_REF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'minimap_ref.png')
_ref = None

def _ref_gray():
    global _ref
    if _ref is None:
        r = cv2.imread(_REF_PATH)
        if r is None:
            raise FileNotFoundError(f'미니맵 레퍼런스 없음: {_REF_PATH}')
        _ref = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    return _ref

def minimap_score(path):
    """우하단 미니맵의 레퍼런스 매칭 점수(0~1). 캡처 실패 시 -1."""
    img = cv2.imread(path)
    if img is None:
        return -1.0
    h, w = img.shape[:2]
    # 1080p 기준으로 정규화 (템플릿 매칭은 스케일 의존적)
    if (w, h) != (1920, 1080):
        img = cv2.resize(img, (1920, 1080))
        h, w = 1080, 1920
    search = cv2.cvtColor(img[int(h*0.70):, int(w*0.78):], cv2.COLOR_BGR2GRAY)
    ref = _ref_gray()
    if search.shape[0] < ref.shape[0] or search.shape[1] < ref.shape[1]:
        return -1.0
    return float(cv2.matchTemplate(search, ref, cv2.TM_CCOEFF_NORMED).max())

def is_gameplay(path, thresh=0.45):
    s = minimap_score(path)
    return s >= thresh, s
