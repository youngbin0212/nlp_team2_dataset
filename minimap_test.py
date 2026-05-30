"""현재 output/output_noheatmap 프레임에 대해 우하단 미니맵 휴리스틱 측정.
게임화면이면 우하단에 협곡(초록/청록) + 복잡한 에지가 있어야 한다."""
import cv2, glob, numpy as np

def metrics(p):
    img = cv2.imread(p)
    h, w = img.shape[:2]
    # 우하단 코너 (대략 우측 20%, 하단 28%)
    roi = img[int(h*0.72):, int(w*0.80):]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (30, 25, 15), (95, 255, 255)).mean()/255
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160).mean()/255
    return w, h, green, edges

print(f'{"green":>6} {"edge":>6}  file')
for p in sorted(glob.glob('output/*.png') + glob.glob('output_noheatmap/*.png')):
    w, h, green, edges = metrics(p)
    print(f'{green:6.3f} {edges:6.3f}  {p}  ({w}x{h})')
