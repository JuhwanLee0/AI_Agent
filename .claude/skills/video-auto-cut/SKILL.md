---
name: video-auto-cut
description: input 폴더에 있는 여러 영상 클립들의 무음(말 없는 조용한 부분)을 FFmpeg으로 자동 컷팅하고, 한국어 자동 자막을 생성하여 이름 순서대로 병합한 최종 영상을 output 폴더에 제작하는 스킬입니다. 사용자가 "영상 무음 잘라줘", "영상 합쳐줘", "영상 자동 편집", "/autocut" 등을 요청할 때 사용하세요.
---

# FFmpeg 스마트 영상 편집 및 자동 자막 엔진 (video-auto-cut)

`input/` 폴더에 넣은 영상 파일들을 자동으로 분석하여, **말이 없는 침묵 구간을 알아서 잘라내고(Jump-cut)**, **한국어 자막(.srt)을 자동으로 입혀** 하나의 완성된 고화질 영상으로 조립합니다.

---

## 🚀 주요 기능

1. **지능형 무음 컷팅 (Silence Detection & Removal)**:
   - `ffmpeg -af silencedetect` 필터를 사용하여 오디오 레벨이 일정 데시벨 이하인 구간을 밀리초 단위로 감지하여 자동 삭제합니다.
2. **한국어 자동 자막 생성 (Auto Subtitle)**:
   - 음성 인식(STT)을 통해 음성을 텍스트로 변환하고, 롱폼 가독성 기준(25자 분할)에 맞추어 타임코드 기반 자막을 생성합니다.
3. **순차 병합 및 렌더링 (Merge & Render)**:
   - 파일 이름 순서대로(`01.mp4`, `02.mp4` 등) 클립들을 결합하고 고화질 자막을 하단에 입혀 `output/final_video.mp4`를 출력합니다.

---

## 📁 디렉토리 구조

```
내프로젝트/
  ├── input/                ← 편집할 원본 영상들을 넣는 폴더 (이름 순서대로 정렬됨)
  │    ├── 01_intro.mp4
  │    ├── 02_body.mp4
  │    └── 03_outro.mp4
  │
  └── output/               ← 최종 완성본이 생성되는 폴더
       ├── final_video.mp4   ← 최종 편집본
       └── subtitle.srt      ← 추출된 한국어 자막
```

---

## 💻 실행 방법

### 기본 실행 (무음 컷 + 자막 + 병합)
```bash
python3 scripts/video_editor/smart_video_editor.py --input input/ --output output/final_video.mp4
```

### 무음 감지 민감도 조절 옵션
```bash
# noise_db: 무음 판정 데시벨 (기본 -30dB), min_silence: 최소 무음 지속 시간 (기본 0.5초)
python3 scripts/video_editor/smart_video_editor.py --input input/ --noise-db -35 --min-silence 0.4
```
