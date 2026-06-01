# LoL 하이라이트 이미지 데이터셋

LoL 하이라이트 영상에서 **게임화면 이미지**를 뽑는다.
용도: ① 이미지 → 초보자 해설 모델 학습  ② 맥락 기반 해설용 context

## 영상 두 종류 (총 1122개)
- **heatmap 있음 (804)** → 유튜브 '많이 본 구간'에서 뽑기 → `output/has_heatmap/`
- **heatmap 없음 (318)** → 영상 5등분해서 뽑기(앞 10초 skip) → `output/no_heatmap/`

## 이미지 거르기
- 영상당 **5장**, **게임화면만** (선수 얼굴·수상화면 등 제외)
- 우하단 **미니맵**이 있는지로 판별 (`minimap_filter.py`)
- 이미지 이름: `영상ID_1~5.png`

## 자막 (해설)
- **순간 해설**: 이미지 시점에 맞는 타임코드 자막 → 직접 수집 (`fetch_transcripts.py`)
- **맥락**: 영상 전체 자막 → 팀원 `lol_subtitles.parquet` (타임코드 없음)
- 합치는 키 = **video_id** (+ 시간)

## 실행
```powershell
# yt-dlp용 JS 런타임 PATH (1회)
$env:PATH = "C:\Users\kimyb\.deno\bin;$env:PATH"

# 1) 이미지 추출 (끊겨도 다시 실행하면 이어서 함)
python build_dataset.py

# 2) 자막 수집 (이미지 끝난 뒤, 끊겨도 이어서 함)
python fetch_transcripts.py

# 진행 상황 확인
.\progress.ps1
```

## 결과물 (Google Drive로 공유, git 제외)
```
output/
  has_heatmap/   이미지 + highlights.csv  (+ highlights_text.csv)
  no_heatmap/    이미지 + highlights.csv  (+ highlights_text.csv)
transcripts/     영상별 타임코드 자막 {video_id}.json
```

## 다른 PC에서 자막만 받기 (팀원용)
이미지는 이미 완성됐고, **자막(`fetch_transcripts.py`)** 만 다른 IP에서 받으면 봇 차단을 피하기 쉽다.

**1. 코드 받기**
```
git clone <레포주소>
```

**2. output 폴더 넣기**
드라이브로 공유받은 `output` 폴더를 clone한 폴더 안에 통째로 넣는다.
(자막 스크립트가 `output/*_highlights.csv` 의 영상 목록을 읽음)

**3. 준비물 설치** (PowerShell)
```powershell
pip install yt-dlp
irm https://deno.land/install.ps1 | iex     # deno (yt-dlp용 JS 런타임)
```

**4. 유튜브 쿠키 넣기** (봇 차단 우회용, 본인 계정)
1. 크롬 웹스토어에서 **"Get cookies.txt LOCALLY"** 확장 설치
2. 크롬에서 **youtube.com 접속** (구글 **로그인** 상태)
3. 확장 아이콘 → **Export**
4. 받은 내용을 폴더 안 **`www.youtube.com_cookies.txt`** 파일에 통째로 붙여넣고 저장
   - ⚠️ 쿠키는 로그인 정보 → 외부 공유 / git push 금지

**5. 실행**
```powershell
$env:PATH = "$HOME\.deno\bin;$env:PATH"
python fetch_transcripts.py
```
- "차단/429"가 떠도 8회 연속이면 알아서 40~80분 쉬었다 재개. 끊겨도 다시 실행하면 이어서 함.

**6. 결과 돌려주기**
다 되면 **`transcripts/` 폴더** + output 안에 생긴 **`*_highlights_text.csv` 2개**를 공유.

## 주요 파일
| 파일 | 설명 |
|---|---|
| build_dataset.py | 이미지 추출 (메인) |
| fetch_transcripts.py | 자막(해설) 수집 |
| minimap_filter.py + minimap_ref.png | 게임화면 판별 |
| scan_heatmap.py / retry_heatmap.py | heatmap 유무로 영상 분류 (목록 생성) |
| has_heatmap.jsonl / no_heatmap.jsonl | 영상 목록 (2종류) |
| lol_subtitles.parquet | 팀원 전체 자막 (맥락용) |
