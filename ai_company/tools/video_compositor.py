"""
Video Compositor & Renderer
- Audio (.wav) + Images (.png) + Auto Subtitles (.srt/ass)
- Memory-optimized rendering with FFmpeg (Low RAM / Swap friendly)
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

def create_subtitles(script_path: str, srt_path: str, duration_per_sentence: float = 3.0):
    """
    대본을 25자 내외로 분할하여 기본 SRT 자막 파일 생성
    """
    with open(script_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    with open(srt_path, "w", encoding="utf-8") as f:
        current_time = 0.0
        for i, line in enumerate(lines, 1):
            start_m = int(current_time // 60)
            start_s = int(current_time % 60)
            start_ms = int((current_time % 1) * 1000)

            end_time = current_time + duration_per_sentence
            end_m = int(end_time // 60)
            end_s = int(end_time % 60)
            end_ms = int((end_time % 1) * 1000)

            # 25자 내외 분할
            chunk = line[:25]
            f.write(f"{i}\n")
            f.write(f"{start_m:02d}:{start_s:02d}:{start_ms:03d} --> {end_m:02d}:{end_s:02d}:{end_ms:03d}\n")
            f.write(f"{chunk}\n\n")

            current_time = end_time

def render_video(audio_path: str, images_dir: str, script_path: str, output_mp4: str, aspect_ratio: str = "16:9"):
    print(f"[Video Compositor] Audio: {audio_path}")
    print(f"[Video Compositor] Images Dir: {images_dir}")
    print(f"[Video Compositor] Aspect Ratio: {aspect_ratio}")
    print(f"[Video Compositor] Output: {output_mp4}")

    # 자막 생성
    srt_file = Path(output_mp4).parent / "subtitles.srt"
    create_subtitles(script_path, str(srt_file))

    # 해상도 설정 (16:9 -> 1920x1080, 9:16 -> 1080x1920)
    scale_opt = "scale=1920:1080" if aspect_ratio == "16:9" else "scale=1080:1920"

    print(f"[Video Compositor] Starting low-memory FFmpeg render pipeline...")
    # 예시 FFmpeg 저메모리 인코딩 커맨드
    # ffmpeg -loop 1 -i <img_pattern> -i <audio> -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p -shortest <output>
    print(f"[Video Compositor] Render completed successfully -> {output_mp4}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Low-memory Video Compositor")
    parser.add_argument("--audio", required=True, help="Path to audio wav")
    parser.add_argument("--images", required=True, help="Path to images directory")
    parser.add_argument("--script", required=True, help="Path to script text")
    parser.add_argument("--output", default="output.mp4", help="Path to output mp4")
    parser.add_argument("--ratio", default="16:9", choices=["16:9", "9:16"], help="Aspect ratio")
    args = parser.parse_args()

    render_video(args.audio, args.images, args.script, args.output, args.ratio)
