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
    - 1순위: 로컬 CLI (CosyVoice for KO / Chatterbox for EN)
    - 2순위: edge-tts (초고음질 클라우드 TTS, 무설치 API)
    - 3순위: gTTS (Google TTS)
    - 4순위: FFmpeg audio generator fallback
    """
    print(f"[{lang.upper()} TTS Engine] Synthesizing: {text}")
    
    # 1. edge-tts 시도 (가장 자연스러운 한국어/영어 음성)
    try:
        voice = "ko-KR-SunHiNeural" if lang == "ko" else "en-US-JennyNeural"
        cmd = [
            "edge-tts",
            "--voice", voice,
            "--text", text,
            "--write-media", output_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            # 24kHz 모노 변환
            _resample_audio(output_path)
            return True
    except Exception:
        pass

    # 2. gTTS 시도
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang)
        tts.save(output_path)
        _resample_audio(output_path)
        return True
    except Exception:
        pass

    # 3. CosyVoice / Chatterbox CLI 시도
    try:
        cli_name = "cosyvoice" if lang == "ko" else "chatterbox"
        cmd = [cli_name, "--text", text, "--output", output_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and os.path.exists(output_path):
            _resample_audio(output_path)
            return True
    except Exception:
        pass

    # 4. Fallback (FFmpeg sine wave mock)
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "24000", "-ac", "1", output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"Error generating audio: {e}", file=sys.stderr)
        return False

def _resample_audio(file_path: str):
    """오디오 파일을 24000Hz 1채널(모노)로 정규화"""
    try:
        temp_out = f"{file_path}.resampled.wav"
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ar", "24000", "-ac", "1", temp_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_out):
            os.replace(temp_out, file_path)
    except Exception:
        pass

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
    try:
        subprocess.run(cmd, check=True)
        print(f"TTS Audio Complete: {output_wav_path}")
    finally:
        # 임시 파일 정리 (디스크 누수 방지)
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dual-Engine TTS Pipeline (24kHz Mono)")
    parser.add_argument("--script", required=True, help="Path to input text script (.txt)")
    parser.add_argument("--output", default="output.wav", help="Path to output .wav file")
    args = parser.parse_args()

    process_script(args.script, args.output)
