---
name: topic-scout
description: YouTube outlier topic scout and evaluation skill based on baseline VPH ratios and 4-fold veto gates. Use when researching high-leverage YouTube video topics.
---

# Topic Scout — 유튜브 주제 선정 판정기

조회수 순위가 아닌 **채널 기준선 대비 시간당 조회수(VPH) 배율**과 **4종 신호 합의**, 그리고 **4중 거부권(Veto Gate)**을 통해 유튜브 주제를 객관적으로 발굴하고 평가하는 스킬입니다.

---

## 3대 핵심 원칙

1. **점수는 코드가, 서술은 AI가**
   - 점수 및 순위 계산은 네트워크를 쓰지 않는 순수 함수 파이썬(`scout_rank.py`)이 전담합니다.
   - LLM은 점수를 절대 만지지 않으며, **글 쓰는 7개 칸**만 채웁니다.
2. **조회수가 아니라 배율로 판정**
   - 큰 채널의 오염된 누적 조회수가 아닌, 해당 채널의 **롱폼(>180초) VPH 중앙값**을 기준선 삼아 **배율(Ratio)**로 계산합니다.
3. **판정을 거부할 줄 알아야 함**
   - 데이터가 부족하거나 쿼터 소진 등으로 오염된 경우(`degraded: true`), 점수를 내지 않고 즉시 판정을 거부(`exit 2`)합니다.

---

## 파이프라인 워크플로우

```
1. scripts/scout_fetch.py (yt-dlp flat스캔 + YouTube API 1유닛/50영상)
   └──> _scout/snapshots/{YYYYMMDD-HHMMSS}.json 스냅샷 저장
2. scripts/scout_rank.py (순수 함수 랭커, 자카드 클러스터링 & 4종 신호 검사)
   └──> candidates, excluded, deduped JSON 출력
3. scripts/check_topic.py (4중 거부권: 명예훼손, 참사, 비진정성, 중복)
   └──> pass / veto 판정
4. LLM 7개 서술 칸 채우기 & 카드 렌더링
   └──> _scout/ledger.jsonl 에 사전등록(preregistered_hit_threshold) 기록
```

---

## AI가 채우는 7개 서술 필드

후보 주제가 확정되면 LLM은 아래 7개 칸만 작성합니다:

1. **제목 후보 3개**: 클릭을 유도하되 어그로가 아닌 명확한 훅이 담긴 제목
2. **썸네일 컨셉 3개**: 텍스트 4단어 이하 + 대비되는 시각적 오브젝트
3. **콜드오픈 첫 문장**: 영상 시작 3초 안에 이탈을 막는 훅
4. **참고 영상 링크**: 아웃라이어를 기록한 레퍼런스 영상 URL
5. **채널 각도**: 내 채널의 정체성/전문성을 접목할 포인트
6. **각도 적합도**: `direct` (그대로 적용 가능) / `reframe` (내 분야로 재해석 필요) / `none` (부적합)
7. **앵글 가설**: "왜 이 주제가 지금 터졌고, 우리 구독자에게 왜 먹힐 것인가"에 대한 가설

---

## 카드 렌더링 템플릿

```markdown
### 🎯 [후보 N] {토픽 대표명}
- **포맷 라우팅**: {matched_format} (설명형 / 사례해부형 / 비교형 / 포맷 미정)
- **배율 요약**: 최대 {max_ratio}배 | 관측 채널 {channel_count}곳 | 최신 영상 {freshest_age_days}일 전
- **신호 합의 ({signal_agreement_count}/4)**:
  - [x/ ] 아웃라이어 강도 (outlier_strength >= 8.0x)
  - [x/ ] 다채널 교차 관측 (cross_channel >= 2개 채널)
  - [x/ ] 최신성/에버그린 (freshness <= 14일 또는 에버그린)
  - [x/ ] 패키징 파워 (packaging_views >= 40만)
- **신뢰도**: {prior_confidence} ({'표본 1개 (단일 채널 관측 - thin)' if prior_confidence == 'thin' else '복수 채널 교차 검증 완료 (high)'})
- **4중 게이트 판정**: 통과 (명예훼손·참사·비진정성·중복 없음)

#### 📝 AI 기획 서술
1. **제목 후보**:
   - A. {제목 1}
   - B. {제목 2}
   - C. {제목 3}
2. **썸네일 컨셉**:
   - A. {시각 요소 + 텍스트}
   - B. {시각 요소 + 텍스트}
   - C. {시각 요소 + 텍스트}
3. **콜드오픈 첫 문장**: "{첫 문장}"
4. **참고 영상**: {video_url} ({ratio}배 / 조회수 {views})
5. **채널 각도**: {내 채널에 접목할 각도}
6. **각도 적합도**: `{direct | reframe | none}`
7. **앵글 가설**: {가설 내용}
```

---

## 사전등록(Pre-registration) 및 성과 원장 (`_scout/ledger.jsonl`)

영상을 제작/업로드하기 전, 반드시 사후 합리화(HARKing)를 방지하기 위해 **사전등록 히트 기준선**을 원장에 기록해야 합니다.

```json
{
  "topic": "2026년 인공지능 수익화 모델",
  "video_id": "업로드_예정_또는_완료_ID",
  "published_at": "YYYY-MM-DD",
  "signal_vector": {"outlier_strength": true, "cross_channel": true, "freshness": true, "packaging_views": true},
  "signal_agreement_count": 4,
  "prior_confidence": "high",
  "preregistered_hit_threshold": 1900,
  "hit_threshold_unit": "views_28d",
  "outcome": null
}
```

> ⚠️ **경고**: `preregistered_hit_threshold`가 비어있는 상태로 발행하지 마세요. 발행 후 채우는 것은 사전등록이 아닙니다.

---

## 실행 명령어 가이드

```bash
# 1. 스냅샷 수집
python3 scripts/scout_fetch.py --config config/topic-scout.json

# 2. 순수 함수 랭킹 실행
python3 scripts/scout_rank.py --config config/topic-scout.json

# 3. 개별 토픽 게이트 검사
python3 scripts/check_topic.py --topic "검사할 주제"
```
