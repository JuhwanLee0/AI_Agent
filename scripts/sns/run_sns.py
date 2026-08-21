#!/usr/bin/env python3
"""
SNS Automation Pipeline CLI (Tavily Step 1 -> Jina Step 2 -> Human Approval -> Threads Publish)
Author: AI Agent Team (Onktree & Ponytail Architecture)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sns.config import DEFAULT_DAILY_CONTENT_COUNT
from scripts.sns.queue_db import QueueDB
from scripts.sns.tavily_scout import TavilyScout
from scripts.sns.jina_verifier import JinaVerifier
from scripts.sns.exporter import SNSExporter
from scripts.sns.threads_publisher import ThreadsPublisher

def cmd_draft(args):
    db = QueueDB()
    scout = TavilyScout()
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    count = args.count

    print(f"\n🚀 [Step 1: Tavily 초안 일괄 기획] 시작")
    print(f"  - 관심 도메인: {domains}")
    print(f"  - 생성 수량: {count}개 (안전 웜업 기본 3개)")
    print(f"  - 예약 일자: {date_str}\n")

    ids = scout.batch_generate_and_queue(
        domain_keywords=domains,
        count=count,
        scheduled_date=date_str,
        db=db,
    )
    print(f"\n✨ 완료! {len(ids)}개의 초안이 성공적으로 적재되었습니다. (DB ID: {ids})")
    print(f"👉 확인 명령어: python3 scripts/sns/run_sns.py list --date {date_str}")

def cmd_verify(args):
    db = QueueDB()
    verifier = JinaVerifier()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    print(f"\n🔍 [Step 2: Jina AI 당일 실시간 2차 검증] 시작")
    print(f"  - 검증 대상 일자: {date_str}\n")

    results = verifier.verify_date_batch(scheduled_date=date_str, db=db)
    if not results:
        print("검증할 대상이 없습니다.")
        return

    print("\n" + "=" * 80)
    print(f"{'ID':<4} | {'상태':<16} | {'주제':<30} | {'검증 요약'}")
    print("-" * 80)
    for r in results:
        status_icon = "✅" if r["status"] == "VERIFIED_READY" else ("🔄" if r["status"] == "AUTO_PATCHED" else "⚠️")
        print(f"{r['item_id']:<4} | {status_icon} {r['status']:<14} | {r['topic'][:28]:<30} | {r['diff_summary']}")
    print("=" * 80)
    print(f"\n👉 최종 승인 및 스레드 발행: python3 scripts/sns/run_sns.py publish --date {date_str}")
    print(f"👉 로컬 파일 내보내기: python3 scripts/sns/run_sns.py export --date {date_str}")

def cmd_publish(args):
    """
    최종 승인 게이트 (Human-in-the-Loop):
    검증 완료된 글을 화면에 보여주고, 사용자 승인(Y/n)을 받아 Threads에 자동 업로드
    """
    db = QueueDB()
    publisher = ThreadsPublisher()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.id:
        items = [db.get_item(args.id)]
        items = [it for it in items if it]
    else:
        # 검증 완료(VERIFIED_READY 또는 AUTO_PATCHED)된 콘텐츠 조회
        all_items = db.get_items_by_date(date_str)
        items = [it for it in all_items if it.get("status") in ("VERIFIED_READY", "AUTO_PATCHED", "DRAFT_SCHEDULED")]

    if not items:
        print(f"[{date_str}] 발행 가능한 검증 완료 콘텐츠가 없습니다.")
        return

    print(f"\n📢 [최종 승인 및 Threads(스레드) 발행 게이트] 총 {len(items)}건 대기 중\n")

    published_count = 0
    for idx, item in enumerate(items, 1):
        print("=" * 75)
        print(f"📌 [{idx}/{len(items)}] ID: {item['id']} | 상태: {item['status']} | 주제: {item['topic']}")
        print(f"🔥 표지 제목: {item['cover_title']}")
        print("-" * 75)
        print("🧵 [스레드 본문 미리보기]:")
        print(item.get("thread_text", "").strip())
        print("-" * 75)

        # 사용자 최종 승인 인터랙션
        if not args.yes:
            confirm = input("👉 위 글을 Threads(스레드)에 지금 발행하시겠습니까? (y/N/s(건너뛰기)): ").strip().lower()
            if confirm not in ("y", "yes", "예"):
                print("⏭️ 건너뜁니다.\n")
                continue

        # Meta Threads API 호출
        print(f"🚀 Threads 포스팅 전송 중...")
        res = publisher.publish_post(text=item["thread_text"])

        if res.get("success"):
            db.update_verification_result(
                item_id=item["id"],
                status="PUBLISHED",
                verification_log=json.dumps({"published_at": datetime.now(timezone.utc).isoformat(), "post_id": res.get("post_id")}, ensure_ascii=False)
            )
            print(f"🎉 [발행 성공] Threads Post ID: {res.get('post_id')}\n")
            published_count += 1
        elif res.get("status") == "STAGED_READY":
            print(f"ℹ️ [스테이징 완료] {res.get('message')}\n")
        else:
            print(f"❌ [발행 실패] {res.get('error')}\n")

    print("=" * 75)
    print(f"✨ 최종 작업 완료: 총 {published_count}개 글이 스레드에 정식 발행되었습니다.\n")

def cmd_list(args):
    db = QueueDB()
    if args.date:
        items = db.get_items_by_date(args.date, status=args.status)
    else:
        items = db.list_items(status=args.status, limit=args.limit)

    if not items:
        print("등록된 큐 항목이 없습니다.")
        return

    print("\n" + "=" * 90)
    print(f"{'ID':<4} | {'일자':<10} | {'상태':<16} | {'카테고리':<10} | {'주제'}")
    print("-" * 90)
    for it in items:
        status_icon = "🎉" if it["status"] == "PUBLISHED" else ("✅" if it["status"] == "VERIFIED_READY" else ("🔄" if it["status"] == "AUTO_PATCHED" else ("⚠️" if it["status"] == "HOLD_ALERT" else "📝")))
        print(f"{it['id']:<4} | {it['scheduled_date']:<10} | {status_icon} {it['status']:<14} | {it['category']:<10} | {it['topic']}")
    print("=" * 90)

def cmd_show(args):
    db = QueueDB()
    item = db.get_item(args.id)
    if not item:
        print(f"ID {args.id} 항목을 찾을 수 없습니다.")
        return

    print("\n" + "=" * 70)
    print(f"📌 [상세 조회] ID: {item['id']} | 상태: {item['status']} | 일자: {item['scheduled_date']}")
    print(f"🎯 주제: {item['topic']}")
    print(f"🔥 표지 카피: {item['cover_title']}")
    print("-" * 70)
    print("🖼️ [카드뉴스 슬라이드 & Whisk 프롬프트]")
    for s in item.get("slides", []):
        print(f"  • {s.get('slide_num')}. {s.get('headline')} : {s.get('content')}")
        print(f"    └ Whisk Prompt: {s.get('whisk_prompt')}")
    print("-" * 70)
    print("🧵 [스레드 본문 텍스트]")
    print(item.get("thread_text"))
    print("-" * 70)
    print("🔎 [핵심 팩트체크 클레임]")
    for c in item.get("core_claims", []):
        print(f"  - {c}")
    if item.get("verification_log"):
        print("-" * 70)
        print("📊 [검증 및 발행 이력]")
        print(item.get("verification_log"))
    print("=" * 70 + "\n")

def cmd_export(args):
    exporter = SNSExporter(output_root=args.out_dir)
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"\n📦 [{date_str}] 산출물 내보내기 진행 중...")
    try:
        out_path = exporter.export_date_batch(date_str)
        print(f"🎉 성공! 모든 파일이 생성되었습니다: {out_path}")
        print(f"   - 카드뉴스 슬라이드: cardnews_slides.md")
        print(f"   - Whisk 프롬프트: whisk_prompts.txt")
        print(f"   - 스레드 텍스트: threads_post.txt")
        print(f"   - 전체 리포트: REPORT.md\n")
    except Exception as e:
        print(f"❌ 내보내기 실패: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="탈-AI 티 SNS (카드뉴스/스레드) 2단계 자동화 파이프라인 (Human-in-the-Loop 승인 게이트)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # draft
    p_draft = subparsers.add_parser("draft", help="Step 1: Tavily 기반 고후킹 초안 일괄 생성 및 큐 적재 (기본 3개 안전 웜업)")
    p_draft.add_argument("--domains", "-d", default="AI 도구,생산성,1인 비즈니스", help="콤마로 구분된 관심 도메인 키워드")
    p_draft.add_argument("--count", "-c", type=int, default=DEFAULT_DAILY_CONTENT_COUNT, help=f"생성할 콘텐츠 개수 (기본 {DEFAULT_DAILY_CONTENT_COUNT}개)")
    p_draft.add_argument("--date", type=str, help="발행 예정 일자 (YYYY-MM-DD, 기본 오늘)")

    # verify
    p_verify = subparsers.add_parser("verify", help="Step 2: Jina AI 기반 당일 실시간 팩트체크 및 자동 스마트 패치")
    p_verify.add_argument("--date", type=str, help="검증할 예약 일자 (YYYY-MM-DD, 기본 오늘)")

    # publish (Human-in-the-Loop Approval Gate)
    p_publish = subparsers.add_parser("publish", help="최종 승인 게이트: 검증된 글 확인 후 Threads(스레드)에 실제 발행")
    p_publish.add_argument("--date", type=str, help="발행할 일자 (YYYY-MM-DD, 기본 오늘)")
    p_publish.add_argument("--id", type=int, help="특정 콘텐츠 단건 발행 ID")
    p_publish.add_argument("--yes", "-y", action="store_true", help="승인 확인 질문 건너뛰고 일괄 발행")

    # list
    p_list = subparsers.add_parser("list", help="큐 목록 조회")
    p_list.add_argument("--date", type=str, help="특정 일자 필터")
    p_list.add_argument("--status", type=str, help="특정 상태 필터 (DRAFT_SCHEDULED, VERIFIED_READY, AUTO_PATCHED, HOLD_ALERT, PUBLISHED)")
    p_list.add_argument("--limit", type=int, default=50, help="조회 개수 제한")

    # show
    p_show = subparsers.add_parser("show", help="단일 콘텐츠 상세 조회")
    p_show.add_argument("--id", type=int, required=True, help="콘텐츠 ID")

    # export
    p_export = subparsers.add_parser("export", help="온트리 1단계 Head 패키지 파일 일괄 내보내기")
    p_export.add_argument("--date", type=str, help="내보낼 일자 (YYYY-MM-DD, 기본 오늘)")
    p_export.add_argument("--out-dir", type=str, help="출력 디렉토리 경로")

    args = parser.parse_args()

    if args.command == "draft":
        cmd_draft(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "export":
        cmd_export(args)

if __name__ == "__main__":
    main()
