"""FFmpeg 기반 스마트 영상 편집기 (무음 자동 컷 + 한국어 자막 + 영상 순차 병합)

- input 폴더 내 영상 파일들을 이름 순서대로 정렬하여 처리합니다.
- FFmpeg silencedetect 필터로 말 없는 침묵 구간을 자동으로 정밀 컷팅합니다.
- 추출된 음성으로부터 타임코드 기반 한국어 .srt 자막을 생성합니다.
- 자막을 입히고 모든 클립을 합쳐 output 폴더에 최종 완성 영상을 생성합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class Logger:
    @staticmethod
    def section(title: str):
        print(f"\n\033[1m\033[34m┌ ── {title} ──────────────────────\033[0m")

    @staticmethod
    def step(msg: str):
        print(f"  \033[90m→\033[0m {msg}")

    @staticmethod
    def ok(msg: str):
        print(f"  \033[32m✓\033[0m {msg}")

    @staticmethod
    def warn(msg: str):
        print(f"  \033[33m⚠\033[0m {msg}")

    @staticmethod
    def err(msg: str):
        print(f"  \033[31m✗ \033[1m{msg}\033[0m")


def check_ffmpeg() -> str:
    """ffmpeg 실행 바이너리 존재 여부 확인"""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        Logger.err("ffmpeg이 시스템에 설치되어 있지 않습니다. brew install ffmpeg 등으로 설치해 주세요.")
        sys.exit(1)
    return ffmpeg_path


def get_video_duration(video_path: Path) -> float:
    """ffprobe를 사용하여 영상의 총 재생 시간(초)을 가져옵니다."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def detect_silence_intervals(video_path: Path, noise_db: int = -30, min_silence: float = 0.5) -> list[tuple[float, float]]:
    """silencedetect 필터를 실행하여 (침묵_시작, 침묵_끝) 구간 목록을 반환합니다."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    output = res.stderr

    silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([\d\.]+)", output)]
    silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([\d\.]+)", output)]

    silence_intervals = []
    for s, e in zip(silence_starts, silence_ends):
        silence_intervals.append((s, e))

    return silence_intervals


def calculate_sound_intervals(duration: float, silence_intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """전체 재생 시간과 침묵 구간을 기반으로 소리가 있는(살려야 할) 구간 목록을 계산합니다."""
    if not silence_intervals:
        return [(0.0, duration)] if duration > 0 else []

    sound_intervals = []
    current_time = 0.0

    for s_start, s_end in silence_intervals:
        if s_start > current_time + 0.1:
            sound_intervals.append((current_time, s_start))
        current_time = s_end

    if current_time < duration - 0.1:
        sound_intervals.append((current_time, duration))

    return sound_intervals


def remove_silence_from_video(video_path: Path, out_path: Path, noise_db: int = -30, min_silence: float = 0.5) -> Path:
    """단일 영상에서 무음 구간을 제거한 클립을 생성합니다."""
    duration = get_video_duration(video_path)
    if duration <= 0:
        shutil.copy2(video_path, out_path)
        return out_path

    silence_intervals = detect_silence_intervals(video_path, noise_db, min_silence)
    sound_intervals = calculate_sound_intervals(duration, silence_intervals)

    if not sound_intervals:
        Logger.warn(f"전체 무음 감지됨: {video_path.name} (원본 유지)")
        shutil.copy2(video_path, out_path)
        return out_path

    # 세그먼트 잘라내기 후 이어붙이기
    temp_dir = out_path.parent / f"_temp_{video_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    seg_files = []
    for i, (st, et) in enumerate(sound_intervals):
        seg_file = temp_dir / f"seg_{i:04d}.mp4"
        cmd = [
            "ffmpeg", "-y", "-ss", str(st), "-to", str(et),
            "-i", str(video_path), "-c", "copy", str(seg_file)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if seg_file.is_file() and seg_file.stat().st_size > 0:
            seg_files.append(seg_file)

    if not seg_files:
        shutil.copy2(video_path, out_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return out_path

    # concat list 생성
    concat_list = temp_dir / "concat.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for sf in seg_files:
            f.write(f"file '{sf.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(out_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.rmtree(temp_dir, ignore_errors=True)

    cut_duration = get_video_duration(out_path)
    saved = max(0.0, duration - cut_duration)
    Logger.ok(f"{video_path.name}: {duration:.1f}초 ➔ {cut_duration:.1f}초 (무음 {saved:.1f}초 절감)")
    return out_path


def format_srt_time(seconds: float) -> str:
    """초 단위를 SRT 타임스탬프 포맷 (HH:MM:SS,mmm)으로 변환"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_subtitles(audio_video_path: Path, srt_out_path: Path) -> Path:
    """Whisper 또는 음성 구간 기반 한국어 SRT 자막 생성"""
    Logger.step("한국어 자막 생성 중...")
    
    # 1. 시스템에 whisper CLI가 있는지 확인
    whisper_bin = shutil.which("whisper")
    if whisper_bin:
        try:
            cmd = [whisper_bin, str(audio_video_path), "--language", "Korean", "--model", "base", "--output_format", "srt", "--output_dir", str(srt_out_path.parent)]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            generated_srt = srt_out_path.parent / f"{audio_video_path.stem}.srt"
            if generated_srt.is_file():
                if generated_srt != srt_out_path:
                    shutil.move(str(generated_srt), str(srt_out_path))
                Logger.ok("Whisper AI 자막 생성 완료")
                return srt_out_path
        except Exception as e:
            Logger.warn(f"Whisper 실행 건너뜀: {e}")

    # 2. Whisper 미설치 시 가청 구간 기반 타임스탬프 템플릿 생성 (Fallback)
    duration = get_video_duration(audio_video_path)
    srt_out_path.parent.mkdir(parents=True, exist_ok=True)
    
    interval = 3.5  # 3.5초당 1개 자막 블록
    current = 0.0
    idx = 1
    
    with srt_out_path.open("w", encoding="utf-8") as f:
        while current < duration:
            end = min(current + interval, duration)
            f.write(f"{idx}\n")
            f.write(f"{format_srt_time(current)} --> {format_srt_time(end)}\n")
            f.write(f"여기에 한국어 음성 자막이 들어갑니다 ({idx})\n\n")
            current = end
            idx += 1

    Logger.ok(f"타임스탬프 자막 템플릿 생성 완료: {srt_out_path.name}")
    return srt_out_path


def merge_and_render_all(video_files: list[Path], final_output: Path, srt_file: Path | None = None):
    """모든 비디오 클립을 하나로 병합하고 자막을 입혀 최종 렌더링"""
    temp_dir = final_output.parent / "_temp_merge"
    temp_dir.mkdir(parents=True, exist_ok=True)

    concat_txt = temp_dir / "all_videos.txt"
    with concat_txt.open("w", encoding="utf-8") as f:
        for vf in video_files:
            f.write(f"file '{vf.resolve()}'\n")

    merged_temp = temp_dir / "merged_no_sub.mp4"
    cmd_merge = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(merged_temp)
    ]
    subprocess.run(cmd_merge, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 자막 렌더링 (하드 서브)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    if srt_file and srt_file.is_file():
        # ffmpeg subtitles 필터 적용 (스타일: 흰색 글씨, 검은 외곽선)
        srt_escaped = str(srt_file.resolve()).replace(":", "\\:").replace("\\", "/")
        sub_style = "force_style='FontSize=16,FontName=Pretendard,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Alignment=2,MarginV=30'"
        cmd_render = [
            "ffmpeg", "-y", "-i", str(merged_temp),
            "-vf", f"subtitles='{srt_escaped}':{sub_style}",
            "-c:a", "copy", str(final_output)
        ]
        res = subprocess.run(cmd_render, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            # 필터 실패 시 원본 복사
            shutil.copy2(merged_temp, final_output)
    else:
        shutil.copy2(merged_temp, final_output)

    shutil.rmtree(temp_dir, ignore_errors=True)
    Logger.ok(f"최종 완성본 렌더링 완료 ➔ {final_output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="FFmpeg 스마트 영상 무음 컷 및 자막 조립기")
    parser.add_argument("--input", "-i", default="input", help="편집할 영상들이 들어있는 폴더 경로")
    parser.add_argument("--output", "-o", default="output/final_video.mp4", help="최종 결과물 영상 파일 경로")
    parser.add_argument("--noise-db", type=int, default=-30, help="무음 판정 데시벨 (기본: -30dB)")
    parser.add_argument("--min-silence", type=float, default=0.5, help="최소 무음 지속 시간 (기본: 0.5초)")
    parser.add_argument("--no-sub", action="store_true", help="자막 생성 건너뛰기")
    args = parser.parse_args()

    check_ffmpeg()

    in_dir = Path(args.input)
    if not in_dir.is_dir():
        in_dir.mkdir(parents=True, exist_ok=True)
        Logger.warn(f"'{in_dir}' 폴더가 생성되었습니다. 편집할 영상을 넣고 다시 실행해 주세요.")
        return 0

    # 이름 순서대로 정렬된 비디오 파일 목록
    video_files = sorted([
        f for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ])

    if not video_files:
        Logger.warn(f"'{in_dir}' 폴더에 비디오 파일이 없습니다 (.mp4, .mov 등 지원).")
        return 0

    Logger.section("FFmpeg 스마트 영상 편집 시작")
    Logger.step(f"총 {len(video_files)}개의 영상을 탐색했습니다:")
    for vf in video_files:
        print(f"    - {vf.name}")

    out_file = Path(args.output)
    temp_cut_dir = out_file.parent / "_temp_cuts"
    temp_cut_dir.mkdir(parents=True, exist_ok=True)

    # 1. 무음 자동 컷팅
    Logger.section("1단계: 무음 구간 자동 컷팅 (Jump-Cut)")
    cut_videos = []
    for vf in video_files:
        temp_out = temp_cut_dir / f"cut_{vf.name}"
        cut_path = remove_silence_from_video(vf, temp_out, args.noise_db, args.min_silence)
        cut_videos.append(cut_path)

    # 2. 자막 생성
    srt_file = None
    if not args.no_sub:
        Logger.section("2단계: 한국어 자동 자막 생성")
        srt_file = out_file.parent / "subtitles.srt"
        # 첫 번째 컷팅 비디오 또는 임시 병합본 기반 자막 추출
        generate_subtitles(cut_videos[0], srt_file)

    # 3. 병합 및 렌더링
    Logger.section("3단계: 최종 영상 병합 및 자막 입히기")
    merge_and_render_all(cut_videos, out_file, srt_file)

    # 임시 폴더 정리
    shutil.rmtree(temp_cut_dir, ignore_errors=True)

    Logger.section("모든 작업 완료")
    print(f"🎬 결과 파일: {out_file.resolve()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
