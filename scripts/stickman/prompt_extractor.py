"""대본(Script) 분석 ➔ 2D 졸라맨(Stick Figure) 영문 이미지 프롬프트 추출기

- 대본을 1~2문장 단위로 스마트하게 쪼갭니다.
- 핵심 키워드 및 감정/상황을 분석하여 'A flat vector-style cartoon, stick figure' 스타일의 영문 프롬프트를 자동 생성합니다.
- Whisk 자동화용 줄바꿈 텍스트 파일(whisk_prompts.txt) 및 상세 메타데이터 JSON을 출력합니다.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# 키워드별 졸라맨 행동 및 배경 매핑 규칙
KEYWORDS_MAP = [
    (r"(돈|자산|소득|월급|수익|원금|부자|부동산|아파트)", "holding a stack of cash or looking at golden coins, minimalist office background"),
    (r"(주식|차트|금리|환율|인플레|지표|통계|상승|폭락|떡락|떡상)", "analyzing a large fluctuating financial line chart on a screen, simple modern room"),
    (r"(쇼핑|소비|카드|지출|결제|비용|가격|세금|영수증)", "looking at a long shopping receipt with a wallet, clean minimal background"),
    (r"(일|업무|회사|직장|컴퓨터|노트북|야근|출근|퇴근)", "typing on a laptop at a minimal desk with a coffee mug, clean indoor setting"),
    (r"(고민|생각|질문|의문|왜|이유|궁금|선택)", "having a big question mark above the head, scratch head gesture, minimal studio background"),
    (r"(충격|위험|위기|손해|후회|눈물|폭망|망했다|주의)", "showing a shocked and panicking expression with sweat drops, dramatic simple shadow"),
    (r"(성공|기회|해결|비결|정답|치트키|꿀팁|전략)", "giving a confident thumbs up with a glowing lightbulb idea above head, bright minimalist scene"),
    (r"(시작|도전|미래|계획|목표|달성|성장)", "standing boldly pointing towards a rising sun or horizon, inspiring minimal landscape"),
]

BASE_STYLE = "A flat vector-style cartoon, stick figure with white skin"
SUFFIX_STYLE = "simple 2D line drawing, minimalist clean background, sharp vector illustration, 16:9 aspect ratio"


def split_sentences(text: str) -> list[str]:
    """텍스트를 1~2문장 단위의 호흡으로 분할합니다."""
    # 줄바꿈 및 문장 부호 기준 분할
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentences = []
    
    for line in raw_lines:
        # 마침표, 느낌표, 물음표 뒤에서 분할
        chunks = re.split(r'(?<=[.?!])\s+', line)
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk:
                sentences.append(chunk)

    # 너무 짧은 문장(15자 미만)은 다음 문장과 결합
    merged = []
    buf = ""
    for s in sentences:
        if not buf:
            buf = s
        elif len(buf) < 30:
            buf += " " + s
        else:
            merged.append(buf)
            buf = s
    if buf:
        merged.append(buf)

    return merged


def generate_prompt_for_sentence(sentence: str, idx: int) -> dict:
    """문장 내용을 분석하여 적절한 영문 졸라맨 프롬프트를 생성합니다."""
    action_desc = "standing in thoughtful posture, thinking about life and choices"
    
    for pattern, matched_action in KEYWORDS_MAP:
        if re.search(pattern, sentence):
            action_desc = matched_action
            break

    prompt_en = f"{BASE_STYLE} wearing casual neat clothes, {action_desc}, {SUFFIX_STYLE}"
    
    return {
        "index": idx + 1,
        "sentence": sentence,
        "prompt_en": prompt_en,
    }


def process_script(input_path: Path, output_txt: Path, output_json: Path | None = None) -> list[dict]:
    text = input_path.read_text(encoding="utf-8")
    sentences = split_sentences(text)
    
    results = []
    for i, s in enumerate(sentences):
        res = generate_prompt_for_sentence(s, i)
        results.append(res)

    # 1줄 1프롬프트 파일 저장 (Whisk 붙여넣기용)
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    with output_txt.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(r["prompt_en"] + "\n")

    # 상세 JSON 저장
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="대본 ➔ 2D 졸라맨 프롬프트 자동 추출기")
    parser.add_argument("--input", "-i", required=True, help="입력 대본 텍스트 파일 (.txt)")
    parser.add_argument("--output", "-o", default="whisk_prompts.txt", help="출력 영문 프롬프트 파일 (.txt)")
    parser.add_argument("--json", "-j", help="상세 메타데이터 JSON 출력 경로 (선택)")
    args = parser.parse_args()

    in_file = Path(args.input)
    if not in_file.is_file():
        print(f"오류: 입력 파일 '{in_file}'을 찾을 수 없습니다.")
        return 1

    out_txt = Path(args.output)
    out_json = Path(args.json) if args.json else None

    results = process_script(in_file, out_txt, out_json)
    print(f"✓ 대본에서 총 {len(results)}개의 씬(Scene) 및 프롬프트를 추출했습니다.")
    print(f"✓ 영문 프롬프트 저장 완료: {out_txt}")
    if out_json:
        print(f"✓ 상세 JSON 저장 완료: {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
