#!/usr/bin/env python3
"""
transcribe_voice.py — 语音消息转文字 (T-013a)

使用百炼 paraformer-v2 将 chat_messages 中的语音消息(msg_type=3)转为文字。
转写结果写回 content 字段，格式：[语音转文字]识别结果

file_url字段存的是云客内部文件hash，需拼成OSS下载URL：
  https://yunke-pcfile.oss-cn-beijing.aliyuncs.com/wechat-voice/msg_{hash}.mp3

用法：
  python3 transcribe_voice.py            # 处理所有待转写语音
  python3 transcribe_voice.py --limit 10  # 只处理前10条（测试用）
  python3 transcribe_voice.py --dry-run   # 只查询不转写
"""

import os
import sys
import time
import logging
import argparse
import requests
from http import HTTPStatus

from supabase import create_client
from dashscope.audio.asr import Transcription

# ============================================================
# 配置
# ============================================================

# 手动加载.env（不依赖python-dotenv）
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dieeejjzbhkpgxdhwlxf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

CUTOFF_DATE = "2025-10-01T00:00:00+00:00"
OSS_BASE = "https://yunke-pcfile.oss-cn-beijing.aliyuncs.com/wechat-voice"

# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ============================================================
# Supabase
# ============================================================

_sb = None

def get_sb():
    global _sb
    if _sb is None:
        if not SUPABASE_KEY:
            log.error("SUPABASE_SERVICE_ROLE_KEY 未设置")
            sys.exit(1)
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

# ============================================================
# 文件URL构造
# ============================================================

def build_oss_url(file_hash):
    """将云客file hash拼成OSS MP3下载URL"""
    return f"{OSS_BASE}/msg_{file_hash}.mp3"

def check_url_accessible(url):
    """HEAD请求检查URL是否可访问"""
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        return resp.status_code == 200
    except Exception:
        return False

# ============================================================
# 查询待转写语音
# ============================================================

def fetch_voice_messages(limit=None):
    """查 msg_type=3, content为空或null, file_url非空, sent_at>=2025-10-01"""
    sb = get_sb()
    messages = []
    offset = 0
    page_size = 1000

    while True:
        end = offset + page_size - 1
        if limit and offset + page_size > limit:
            end = offset + limit - len(messages) - 1

        resp = sb.table("chat_messages") \
            .select("id, file_url, msg_svr_id, sent_at") \
            .eq("msg_type", 3) \
            .gte("sent_at", CUTOFF_DATE) \
            .or_("content.is.null,content.eq.") \
            .not_.is_("file_url", "null") \
            .neq("file_url", "") \
            .order("sent_at", desc=False) \
            .range(offset, end) \
            .execute()

        batch = resp.data or []
        messages.extend(batch)

        if len(batch) < page_size:
            break
        if limit and len(messages) >= limit:
            break
        offset += page_size

    if limit:
        messages = messages[:limit]

    return messages

# ============================================================
# 转写单条语音
# ============================================================

def transcribe_one(mp3_url):
    """
    提交OSS MP3 URL到 paraformer-v2 转写，返回文字。
    失败返回 None，空结果返回 ""。
    """
    try:
        # 提交异步转写任务
        task_resp = Transcription.async_call(
            model="paraformer-v2",
            file_urls=[mp3_url],
            language_hints=["zh", "en"],
            api_key=DASHSCOPE_API_KEY,
        )

        if task_resp.status_code != HTTPStatus.OK:
            log.warning(f"  async_call 失败: code={task_resp.status_code}, msg={task_resp.message}")
            return None

        task_id = task_resp.output.task_id

        # 等待完成
        result = Transcription.wait(
            task=task_id,
            api_key=DASHSCOPE_API_KEY,
        )

        if result.status_code != HTTPStatus.OK:
            log.warning(f"  wait 失败: code={result.status_code}, msg={result.message}")
            return None

        # 解析结果
        output = result.output
        results = output.get("results") if isinstance(output, dict) else getattr(output, "results", None)
        if not results or len(results) == 0:
            log.warning("  无 results")
            return None

        first = results[0]
        status = first.get("subtask_status", "")
        if status != "SUCCEEDED":
            log.warning(f"  子任务状态: {status}")
            return None

        transcription_url = first.get("transcription_url", "")
        if not transcription_url:
            log.warning("  无 transcription_url")
            return None

        # 下载转写结果JSON
        resp = requests.get(transcription_url, timeout=30)
        resp.raise_for_status()
        trans_data = resp.json()

        transcripts = trans_data.get("transcripts", [])
        if not transcripts:
            return ""

        text = transcripts[0].get("text", "").strip()
        return text

    except Exception as e:
        log.warning(f"  转写异常: {e}")
        return None

# ============================================================
# 更新content
# ============================================================

def update_content(msg_id, text):
    """写回content字段"""
    content = f"[语音转文字]{text}"
    get_sb().table("chat_messages").update({"content": content}).eq("id", msg_id).execute()

# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="语音消息转文字 (T-013a)")
    parser.add_argument("--limit", type=int, help="只处理前N条")
    parser.add_argument("--dry-run", action="store_true", help="只查询不转写")
    args = parser.parse_args()

    log.info("=" * 50)
    log.info("transcribe_voice.py 启动 (T-013a)")

    if not DASHSCOPE_API_KEY:
        log.error("DASHSCOPE_API_KEY 未设置")
        sys.exit(1)

    # 查询待处理消息
    messages = fetch_voice_messages(limit=args.limit)
    log.info(f"待转写语音消息: {len(messages)} 条")

    if not messages:
        log.info("无需处理，退出")
        return

    if args.dry_run:
        for i, msg in enumerate(messages[:20]):
            oss_url = build_oss_url(msg["file_url"])
            accessible = check_url_accessible(oss_url)
            log.info(f"  [{i+1}] sent_at={msg['sent_at']} accessible={accessible} url={oss_url}")
        if len(messages) > 20:
            log.info(f"  ... 还有 {len(messages) - 20} 条")
        return

    success = 0
    failed = 0
    empty = 0
    skipped = 0

    for i, msg in enumerate(messages):
        file_hash = msg["file_url"]
        msg_id = msg["id"]
        mp3_url = build_oss_url(file_hash)

        log.info(f"[{i+1}/{len(messages)}] msg_svr_id={msg.get('msg_svr_id', '?')} sent_at={msg['sent_at']}")

        # 先检查文件是否可访问
        if not check_url_accessible(mp3_url):
            skipped += 1
            log.info(f"  跳过: OSS文件不存在 ({file_hash})")
            continue

        text = transcribe_one(mp3_url)

        if text is None:
            failed += 1
            log.warning(f"  转写失败")
        elif text == "":
            empty += 1
            update_content(msg_id, "")
            log.info("  空结果（静音/极短）")
        else:
            success += 1
            update_content(msg_id, text)
            preview = text[:60] + ("..." if len(text) > 60 else "")
            log.info(f"  OK: {preview}")

        # 转写间隔（避免DashScope限流）
        if i < len(messages) - 1:
            time.sleep(0.5)

    log.info("-" * 50)
    log.info(f"完成: 成功={success}, 空={empty}, 失败={failed}, 跳过(OSS不存在)={skipped}, 总计={len(messages)}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
