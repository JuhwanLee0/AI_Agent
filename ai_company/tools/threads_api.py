import os
import json
import logging
import requests
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ThreadsApiTool")

class ThreadsApiTool:
    """
    Meta Threads 공식 Graph API 도구
    - 텍스트 및 이미지 스레드 발행
    - 스레드 답글(Reply) 발행
    - 스레드 포스팅 상태 조회
    """
    def __init__(self, user_id: Optional[str] = None, access_token: Optional[str] = None):
        self.user_id = user_id or os.getenv("THREADS_USER_ID")
        self.access_token = access_token or os.getenv("THREADS_ACCESS_TOKEN")
        self.base_url = "https://graph.threads.net/v1.0"

    def is_configured(self) -> bool:
        """API 연동을 위한 환경변수 설정 여부 확인"""
        return bool(self.user_id and self.access_token)

    def publish_text(self, text: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
        """
        스레드 텍스트 게시물 또는 답글 발행 (2-Step Graph API)
        500자 초과 시 자동으로 여러 개의 스레드로 분할하여 답글(Reply) 체이닝 발행
        """
        if not self.is_configured():
            logger.warning("[Threads] THREADS_USER_ID 또는 THREADS_ACCESS_TOKEN 미설정 상태 (가상 완료 처리)")
            return {
                "success": False,
                "status": "STAGED_READY",
                "message": ".env에 THREADS_USER_ID와 THREADS_ACCESS_TOKEN을 입력하면 실제 스레드에 즉시 게시됩니다.",
                "preview": text[:200]
            }

        # 500자 제한 처리 (480자 단위 분할)
        chunks = []
        max_len = 480
        remaining = text.strip()
        while len(remaining) > max_len:
            # 단어 단위 분할
            idx = remaining.rfind("\n", 0, max_len)
            if idx == -1:
                idx = remaining.rfind(" ", 0, max_len)
            if idx == -1:
                idx = max_len
            chunks.append(remaining[:idx].strip())
            remaining = remaining[idx:].strip()
        if remaining:
            chunks.append(remaining)

        post_ids = []
        current_reply_id = reply_to_id

        for idx, chunk in enumerate(chunks):
            try:
                # 1. 미디어 컨테이너 생성
                container_url = f"{self.base_url}/{self.user_id}/threads"
                payload = {
                    "access_token": self.access_token,
                    "media_type": "TEXT",
                    "text": chunk
                }
                if current_reply_id:
                    payload["reply_to_id"] = current_reply_id

                res = requests.post(container_url, data=payload, timeout=30)
                res.raise_for_status()
                creation_data = res.json()
                creation_id = creation_data.get("id")

                if not creation_id:
                    return {"success": False, "error": f"컨테이너 ID 생성 실패: {creation_data}"}

                # 2. 컨테이너 발행
                publish_url = f"{self.base_url}/{self.user_id}/threads_publish"
                pub_payload = {
                    "access_token": self.access_token,
                    "creation_id": creation_id
                }
                pub_res = requests.post(publish_url, data=pub_payload, timeout=30)
                pub_res.raise_for_status()
                pub_data = pub_res.json()
                post_id = pub_data.get("id")
                
                post_ids.append(post_id)
                current_reply_id = post_id # 다음 스레드는 이번 스레드의 답글로 연결

                logger.info(f"[Threads] 🎉 포스팅 완료 (Chunk {idx+1}/{len(chunks)}, Post ID: {post_id})")

            except Exception as e:
                logger.error(f"[Threads] publish_text 오류 (Chunk {idx+1}): {e}")
                return {
                    "success": False,
                    "published_ids": post_ids,
                    "error": str(e)
                }

        return {
            "success": True,
            "status": "PUBLISHED",
            "post_id": post_ids[0] if post_ids else None,
            "all_post_ids": post_ids,
            "message": f"스레드에 총 {len(post_ids)}개 연결 포스트가 성공적으로 발행되었습니다."
        }

    def publish_image(self, text: str, image_url: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
        """
        이미지가 포함된 스레드 게시물 발행
        """
        if not self.is_configured():
            return {
                "success": False,
                "status": "STAGED_READY",
                "message": ".env에 Threads 토큰이 설정되지 않았습니다.",
                "preview": f"[이미지: {image_url}] {text[:100]}"
            }

        try:
            container_url = f"{self.base_url}/{self.user_id}/threads"
            payload = {
                "access_token": self.access_token,
                "media_type": "IMAGE",
                "image_url": image_url,
                "text": text
            }
            if reply_to_id:
                payload["reply_to_id"] = reply_to_id

            res = requests.post(container_url, data=payload, timeout=30)
            res.raise_for_status()
            creation_id = res.json().get("id")

            # 발행
            publish_url = f"{self.base_url}/{self.user_id}/threads_publish"
            pub_res = requests.post(publish_url, data={"access_token": self.access_token, "creation_id": creation_id}, timeout=30)
            pub_res.raise_for_status()
            post_id = pub_res.json().get("id")

            return {
                "success": True,
                "status": "PUBLISHED",
                "post_id": post_id,
                "message": "이미지 스레드가 성공적으로 발행되었습니다."
            }
        except Exception as e:
            logger.error(f"[Threads] publish_image 오류: {e}")
            return {"success": False, "error": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Threads 사용자 프로필 정보 조회"""
        if not self.is_configured():
            return {"success": False, "error": "Threads 토큰 미설정"}
        try:
            url = f"{self.base_url}/{self.user_id}?fields=id,username,threads_profile_picture_url,threads_biography&access_token={self.access_token}"
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            return {"success": True, "data": res.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    tool = ThreadsApiTool()
    print("Threads Configured:", tool.is_configured())
