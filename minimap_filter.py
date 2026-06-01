"""미니맵 템플릿 매칭으로 '게임화면' 판별 (cv2만 사용, GPU/torch 불필요).

소환사 협곡 지형은 동일하지만 방송(LCK/월즈, 시즌)마다 미니맵 위치·크기가 조금씩 다르다.
→ 여러 레퍼런스(minimap_ref*.png) 각각을 여러 배율로 맞춰보고 그중 최고 점수 사용.

검증(1080p, 2026 LCK + 2025 월즈): 게임화면 0.71~1.0 / 인트로·선수컷·수상화면 <0.30
→ 임계값 0.50 권장.
레퍼런스 추가법: 잘 안 잡히는 방송의 게임프레임에서 우하단 미니맵을 잘라 minimap_refN.png 로 저장.
"""
import os
import glob
import cv2

_DIR = os.path.dirname(os.path.abspath(__file__))
_SCALES = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
_refs = None

def _load_refs():
    global _refs
    if _refs is None:
        paths = sorted(glob.glob(os.path.join(_DIR, 'minimap_ref*.png')))
        if not paths:
            raise FileNotFoundError('미니맵 레퍼런스(minimap_ref*.png) 없음')
        _refs = [cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2GRAY) for p in paths]
    return _refs

def minimap_score(path):
    """우하단 미니맵을 여러 레퍼런스·배율로 매칭한 최고 점수(0~1). 실패 시 -1."""
    img = cv2.imread(path)
    if img is None:
        return -1.0
    h, w = img.shape[:2]
    if (w, h) != (1920, 1080):       # 1080p로 정규화
        img = cv2.resize(img, (1920, 1080))
        h, w = 1080, 1920
    search = cv2.cvtColor(img[int(h*0.66):, int(w*0.78):], cv2.COLOR_BGR2GRAY)
    best = -1.0
    for ref in _load_refs():
        rh, rw = ref.shape
        for s in _SCALES:
            nr = cv2.resize(ref, (max(1, int(rw*s)), max(1, int(rh*s))))
            if nr.shape[0] > search.shape[0] or nr.shape[1] > search.shape[1]:
                continue
            m = cv2.matchTemplate(search, nr, cv2.TM_CCOEFF_NORMED).max()
            if m > best:
                best = float(m)
    return best

def is_gameplay(path, thresh=0.50):
    s = minimap_score(path)
    return s >= thresh, s
