import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from scripts.sns.config import OUTPUT_DIR
from scripts.sns.queue_db import QueueDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SNSExporter")

class SNSExporter:
    def __init__(self, output_root: Optional[Path] = None):
        self.output_root = Path(output_root or OUTPUT_DIR)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def export_item(self, item: Dict[str, Any], target_dir: Path):
        target_dir.mkdir(parents=True, exist_ok=True)

        slides = item.get("slides", [])
        cover_title = item.get("cover_title", "")
        thread_text = item.get("thread_text", "")
        topic = item.get("topic", "")
        category = item.get("category", "")
        status = item.get("status", "")
        claims = item.get("core_claims", [])
        source_urls = item.get("source_urls", [])

        # 1. whisk_prompts.txt (Google Labs Whisk 1줄 1프롬프트)
        whisk_lines = []
        for s in slides:
            prompt = s.get("whisk_prompt", "").strip()
            if prompt:
                whisk_lines.append(prompt)

        (target_dir / "whisk_prompts.txt").write_text("\n".join(whisk_lines), encoding="utf-8")

        # 2. cardnews_slides.md (사람이 캔바/미리캔버스에 넣기 쉬운 슬라이드별 대본)
        slides_md = []
        slides_md.append(f"# 📱 [카드뉴스] {cover_title}\n")
        slides_md.append(f"- **카테고리**: {category}")
        slides_md.append(f"- **주제**: {topic}")
        slides_md.append(f"- **상태**: `{status}`\n")
        slides_md.append("---")
        slides_md.append("## 📌 [표지] 1.png")
        slides_md.append(f"**메인 카피**: {cover_title}\n")

        for s in slides:
            s_num = s.get("slide_num", 1)
            headline = s.get("headline", "")
            content = s.get("content", "")
            whisk_p = s.get("whisk_prompt", "")
            slides_md.append(f"## 🖼️ [슬라이드 {s_num}] {s_num}.png")
            slides_md.append(f"**헤드라인**: {headline}")
            slides_md.append(f"**본문**: {content}")
            slides_md.append(f"> **Whisk 이미지 프롬프트**: `{whisk_p}`\n")

        (target_dir / "cardnews_slides.md").write_text("\n".join(slides_md), encoding="utf-8")

        # 3. threads_post.txt (스레드 전용 텍스트)
        (target_dir / "threads_post.txt").write_text(thread_text, encoding="utf-8")

        # 4. metadata.json
        (target_dir / "metadata.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_date_batch(self, scheduled_date: str, db: Optional[QueueDB] = None) -> Path:
        db = db or QueueDB()
        items = db.get_items_by_date(scheduled_date)
        if not items:
            raise ValueError(f"[{scheduled_date}] 내보낼 콘텐츠가 없습니다.")

        batch_dir = self.output_root / scheduled_date
        batch_dir.mkdir(parents=True, exist_ok=True)

        summary_rows = []
        for idx, item in enumerate(items, 1):
            clean_topic = "".join(c for c in item.get("topic", "") if c.isalnum() or c in " _-")[:25].strip()
            item_folder_name = f"{idx:02d}_{clean_topic}"
            item_dir = batch_dir / item_folder_name
            self.export_item(item, item_dir)

            v_log_str = item.get("verification_log") or "{}"
            try:
                v_log = json.loads(v_log_str)
            except Exception:
                v_log = {"diff_summary": v_log_str}

            summary_rows.append({
                "num": idx,
                "id": item["id"],
                "topic": item.get("topic"),
                "status": item.get("status"),
                "diff": v_log.get("diff_summary", "-"),
                "folder": item_folder_name,
            })

        # Generate summary REPORT.md
        report_md = [
            f"# 📊 [{scheduled_date}] SNS 일괄 검증 및 산출물 리포트\n",
            f"총 **{len(items)}개**의 콘텐츠가 온트리 1단계(Head) 패키지로 준비되었습니다.\n",
            "| # | 상태 | 주제 | 검증 및 교정 내역 | 폴더 |",
            "| :-: | :---: | :--- | :--- | :--- |",
        ]

        for r in summary_rows:
            status_icon = "✅" if r["status"] == "VERIFIED_READY" else ("🔄" if r["status"] == "AUTO_PATCHED" else "⚠️")
            report_md.append(f"| {r['num']} | {status_icon} `{r['status']}` | {r['topic']} | {r['diff']} | `{r['folder']}/` |")

        report_md.append("\n## 💡 활용 방법")
        report_md.append("1. **스레드(Threads)**: 각 폴더의 `threads_post.txt` 내용을 복사하여 바로 포스팅 (이미지 불필요).")
        report_md.append("2. **Google Whisk 이미지 수집**: `whisk_prompts.txt` 프롬프트들을 Whisk에 일괄 넣어 `1.png ~ n.png` 이미지 세트 생성.")
        report_md.append("3. **카드뉴스 완성**: `cardnews_slides.md` 텍스트와 Whisk 이미지를 캔바/미리캔버스 템플릿에 배치하여 완성.\n")

        (batch_dir / "REPORT.md").write_text("\n".join(report_md), encoding="utf-8")
        logger.info(f"[{scheduled_date}] 내보내기 완료: {batch_dir}")
        return batch_dir
