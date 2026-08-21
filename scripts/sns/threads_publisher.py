import json
import logging
import requests
from typing import Dict, Any, Optional
from scripts.sns.config import THREADS_USER_ID, THREADS_ACCESS_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ThreadsPublisher")

class ThreadsPublisher:
    """
    Meta Threads 공식 Graph API 연동 퍼블리셔
    - 최종 사용자 승인(Human-in-the-Loop) 시 스레드에 글/이미지 업로드
    """
    def __init__(self, user_id: Optional[str] = None, access_token: Optional[str] = None):
        self.user_id = user_id or THREADS_USER_ID
        self.access_token = access_token or THREADS_ACCESS_TOKEN

    def is_configured(self) -> bool:
        return bool(self.user_id and self.access_token)

    def publish_post(self, text: str, image_url: Optional[str] = None) -> Dict[str, Any]:
        """
        스레드 글 포스팅 (2-Step Graph API)
        1단계: Container 생성 (POST https://graph.threads.net/v1.0/{user_id}/threads)
        2단계: Container 발행 (POST https://graph.threads.net/v1.0/{user_id}/threads_publish)
        """
        if not self.is_configured():
            logger.warning("[Threads] THREADS_USER_ID 또는 THREADS_ACCESS_TOKEN이 .env에 설정되지 않았습니다. (테스트/스테이징 모드로 기록)")
            return {
                "success": False,
                "status": "STAGED_READY",
                "message": ".env 파일에 THREADS_ACCESS_TOKEN과 THREADS_USER_ID를 입력하면 즉시 실제 스레드에 게시됩니다.",
                "post_text_preview": text[:100] + "...",
            }

        try:
            # 1. 미디어 컨테이너 생성
            container_url = f"https://graph.threads.net/v1.0/{self.user_id}/threads"
            payload = {
                "access_token": self.access_token,
                "text": text,
            }
            if image_url:
                payload["media_type"] = "IMAGE"
                payload["image_url"] = image_url
            else:
                payload["media_type"] = "TEXT"

            res = requests.post(container_url, data=payload, timeout=30)
            res.raise_for_status()
            container_data = res.json()
            creation_id = container_data.get("id")

            if not creation_id:
                raise ValueError(f"컨테이너 생성 실패: {container_data}")

            # 2. 컨테이너 실제 발행
            publish_url = f"https://graph.threads.net/v1.0/{self.user_id}/threads_publish"
            pub_payload = {
                "access_token": self.access_token,
                "creation_id": creation_id,
            }
            pub_res = requests.post(publish_url, data=pub_payload, timeout=30)
            pub_res.raise_for_status()
            pub_data = pub_res.json()
            post_id = pub_data.get("id")

            logger.info(f"[Threads] 🎉 포스팅 성공! (Post ID: {post_id})")
            return {
                "success": True,
                "status": "PUBLISHED",
                "post_id": post_id,
                "message": "스레드에 성공적으로 발행되었습니다.",
            }
        except Exception as e:
            logger.error(f"[Threads] 포스팅 API 오류: {e}")
            return {
                "success": False,
                "status": "ERROR",
                "error": str(e),
            }
