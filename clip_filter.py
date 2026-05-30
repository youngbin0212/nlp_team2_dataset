"""CLIP 제로샷으로 '게임화면 vs 비게임(선수/캐스터/관중/타이틀)' 판별.
- 게임화면이면 구석에 작은 페이스캠이 있어도 통과(전체적으로 게임 스크린샷이므로).
- is_gameplay(path) -> (bool, game_prob)
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
import torch
import open_clip
from PIL import Image

MODEL_NAME = 'ViT-B-32'
PRETRAINED = 'laion2b_s34b_b79k'

GAME_PROMPTS = [
    "a League of Legends gameplay screenshot with minimap and HUD",
    "a MOBA video game screen with champions, health bars and a minimap",
    "in-game footage of League of Legends on Summoner's Rift",
]
NONGAME_PROMPTS = [
    "a close-up photo of a person's face",
    "esports players sitting at computers on a stage",
    "a television studio with casters or commentators talking",
    "a crowd of spectators in an arena",
    "a logo, title card, replay tag, or text screen",
]

_state = {}

def _load():
    if _state:
        return _state
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=PRETRAINED)
    tokenizer = open_clip.get_tokenizer(MODEL_NAME)
    model.to(device).eval()
    prompts = GAME_PROMPTS + NONGAME_PROMPTS
    with torch.no_grad():
        tok = tokenizer(prompts).to(device)
        tf = model.encode_text(tok)
        tf /= tf.norm(dim=-1, keepdim=True)
    _state.update(model=model, preprocess=preprocess, device=device,
                  text_feat=tf, n_game=len(GAME_PROMPTS))
    return _state

def game_prob(path):
    """게임화면일 확률(0~1) 반환."""
    s = _load()
    img = s['preprocess'](Image.open(path).convert('RGB')).unsqueeze(0).to(s['device'])
    with torch.no_grad():
        f = s['model'].encode_image(img)
        f /= f.norm(dim=-1, keepdim=True)
        probs = (100.0 * f @ s['text_feat'].T).softmax(dim=-1)
    return probs[0, :s['n_game']].sum().item()

def is_gameplay(path, thresh=0.5):
    p = game_prob(path)
    return p >= thresh, p

if __name__ == '__main__':
    # 로딩 확인(모델 다운로드 트리거)
    s = _load()
    print('CLIP 로드 완료:', MODEL_NAME, PRETRAINED, '| device =', s['device'])
