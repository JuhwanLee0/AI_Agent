import os
import sys
import argparse
import subprocess
import shutil
from pathlib import Path
from typing import List

def wrap_text_lines(text: str, max_chars: int = 25) -> List[str]:
    """
    단어가 중간에 잘리지 않도록 25자 내외로 스마트 분할
    """
    if len(text) <= max_chars:
        return [text]
    
    words = text.split()
    chunks = []
    current_chunk = []
    current_len = 0

    for word in words:
        if current_len + len(word) + (1 if current_chunk else 0) <= max_chars:
            current_chunk.append(word)
            current_len += len(word) + (1 if len(current_chunk) > 1 else 0)
        else:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_len = len(word)

    if current_chunk:
        chunks.append(" ".join(current_chunk))
        
    return chunks or [text[:max_chars]]

def create_subtitles(script_path: str, srt_path: str, total_duration: float = None, duration_per_sentence: float = 3.0):
    """
    대본을 스마트 분할하여 타이밍이 맞는 SRT 자막 파일 생성
    """
    with open(script_path, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    # 25자 내외로 스마트 분할된 문장 리스트 생성
    lines = []
    for raw in raw_lines:
        lines.extend(wrap_text_lines(raw, max_chars=25))

    if not lines:
        return

    # 오디오 총 길이가 주어진 경우 균등 배분
    if total_duration and total_duration > 0:
        duration_per_sentence = max(1.0, total_duration / len(lines))

    with open(srt_path, "w", encoding="utf-8") as f:
        current_time = 0.0
        for i, chunk in enumerate(lines, 1):
            start_m = int(current_time // 60)
            start_s = int(current_time % 60)
            start_ms = int((current_time % 1) * 1000)

            end_time = current_time + duration_per_sentence
            end_m = int(end_time // 60)
            end_s = int(end_time % 60)
            end_ms = int((end_time % 1) * 1000)

            f.write(f"{i}\n")
            f.write(f"{start_m:02d}:{start_s:02d}:{start_ms:03d} --> {end_m:02d}:{end_s:02d}:{end_ms:03d}\n")
            f.write(f"{chunk}\n\n")

            current_time = end_time

def get_media_duration(file_path: str) -> float:
    """ffprobe를 통해 오디오/비디오 길이(초) 추출"""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def render_video(audio_path: str, images_dir: str, script_path: str, output_mp4: str, aspect_ratio: str = "16:9") -> bool:
    """
    저메모리(Low-RAM/Swap) 최적화 FFmpeg 렌더링 파이프라인
    - Audio (.wav) + Images (.png) + Subtitles (.srt) -> MP4
    """
    print(f"[Video Compositor] Audio: {audio_path}")
    print(f"[Video Compositor] Images Dir: {images_dir}")
    print(f"[Video Compositor] Aspect Ratio: {aspect_ratio}")
    print(f"[Video Compositor] Output: {output_mp4}")

    out_dir = Path(output_mp4).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 오디오 길이 계산 및 자막 생성
    audio_dur = get_media_duration(audio_path)
    srt_file = out_dir / "subtitles.srt"
    create_subtitles(script_path, str(srt_file), total_duration=audio_dur)

    # 2. 이미지 파일 탐색
    img_files = sorted([
        str(p) for p in Path(images_dir).glob("*.png")
    ] + [
        str(p) for p in Path(images_dir).glob("*.jpg")
    ]) if os.path.exists(images_dir) else []

    # 해상도 설정 (16:9 -> 1920x1080, 9:16 -> 1080x1920)
    scale_opt = "scale=1920:1080" if aspect_ratio == "16:9" else "scale=1080:1920"

    print(f"[Video Compositor] Starting low-memory FFmpeg render pipeline...")
    
    # 이미지가 없을 경우 블랙 백그라운드 영상 생성
    if not img_files:
        video_input = ["-f", "lavfi", "-i", f"color=c=black:s={'1920x1080' if aspect_ratio == '16:9' else '1080x1920'}:r=24"]
    else:
        # 단일 이미지 또는 이미지 루프 처리
        video_input = ["-loop", "1", "-i", img_files[0]]

    cmd = [
        "ffmpeg", "-y",
        *video_input,
        "-i", audio_path,
        "-vf", f"{scale_opt}:force_original_aspect_ratio=decrease,pad={'1920:1080' if aspect_ratio == '16:9' else '1080:1920'}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        output_mp4
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[Video Compositor] Render completed successfully -> {output_mp4}")
        return True
    except Exception as e:
        print(f"[Video Compositor] FFmpeg execution error: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Low-memory Video Compositor")
    parser.add_argument("--audio", required=True, help="Path to audio wav")
    parser.add_argument("--images", required=True, help="Path to images directory")
    parser.add_argument("--script", required=True, help="Path to script text")
    parser.add_argument("--output", default="output.mp4", help="Path to output mp4")
    parser.add_argument("--ratio", default="16:9", choices=["16:9", "9:16"], help="Aspect ratio")
    args = parser.parse_args()

    render_video(args.audio, args.images, args.script, args.output, args.ratio)
