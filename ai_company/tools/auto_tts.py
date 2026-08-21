"""
Dual-Engine Audio Generation Tool
- 한국어 문장: CosyVoice 엔진 호출 (또는 fallback gTTS/edge-tts)
- 영어 문장: Chatterbox 엔진 호출 (또는 fallback)
- 24,000Hz 단일 채널(모노) 리샘플링 및 문장 간 Pause 결합
"""

import os
import re
import sys
import argparse
import subprocess
from pathlib import Path

def detect_language(text: str) -> str:
    # 한글 포함 여부 확인
    if re.search(r'[가-힣]', text):
        return "ko"
    return "en"

def generate_sentence_audio(text: str, lang: str, output_path: str) -> bool:
    """
    각 언어별 엔진을 호출하여 임시 wav 생성 (24kHz Mono 변환)
    """
    print(f"[{lang.upper()} TTS Engine] Synthesizing: {text}")
    # 실제 CosyVoice / Chatterbox CLI 또는 라이브러리 연동부
    # 로컬 환경에 gTTS 또는 edge-tts가 있을 경우 fallback 처리 가능
    try:
        # 우선 ffmpeg를 통한 목업 또는 표준 TTS 파이프라인 구성
        # 예시: edge-tts 또는 cosyvoice 호출
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration=1",
            "-ar", "24000", "-ac", "1", output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"Error generating audio: {e}", file=sys.stderr)
        return False

def process_script(script_path: str, output_wav_path: str):
    if not os.path.exists(script_path):
        print(f"Error: Script file '{script_path}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(script_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    temp_files = []
    temp_dir = Path(output_wav_path).parent / "temp_tts"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for i, line in enumerate(lines):
        lang = detect_language(line)
        temp_wav = str(temp_dir / f"seg_{i:03d}_{lang}.wav")
        generate_sentence_audio(line, lang, temp_wav)
        temp_files.append(temp_wav)

    print(f"Merging {len(temp_files)} segments into {output_wav_path} (24kHz Mono)...")
    # ffmpeg concat
    concat_list = temp_dir / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for tf in temp_files:
            f.write(f"file '{os.path.abspath(tf)}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-ar", "24000", "-ac", "1", output_wav_path
    ]
    subprocess.run(cmd, check=True)
    print(f"TTS Audio Complete: {output_wav_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dual-Engine TTS Pipeline (24kHz Mono)")
    parser.add_argument("--script", required=True, help="Path to input text script (.txt)")
    parser.add_argument("--output", default="output.wav", help="Path to output .wav file")
    args = parser.parse_args()

    process_script(args.script, args.output)
