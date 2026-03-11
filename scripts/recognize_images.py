#!/usr/bin/env python3
"""
T-013b: 图片识别 — 用百炼 qwen-vl-plus 识别 chat_messages 中的图片
查 msg_type=2 且 content 为空且 file_url 非空且 sent_at>=2025-10-01，
调 qwen-vl-plus 识别后写回 content 字段，格式 [图片识别]结果
"""

import os, sys, time, logging
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from supabase import create_client

# ── 日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("recognize_images")

# ── 环境变量 ──────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dieeejjzbhkpgxdhwlxf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

if not SUPABASE_KEY:
    log.error("SUPABASE_SERVICE_ROLE_KEY 未设置"); sys.exit(1)
if not DASHSCOPE_API_KEY:
    log.error("DASHSCOPE_API_KEY 未设置"); sys.exit(1)

# ── 客户端 ────────────────────────────────────────────
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

vl_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

VL_MODEL = "qwen-vl-plus"
PROMPT = "简要描述图片内容，家具产品报价相关详细说明，30字以内"

# ── 查询待识别图片 ────────────────────────────────────
def fetch_pending_images():
    """分页查出所有待识别图片记录"""
    rows = []
    page_size = 500
    offset = 0
    while True:
        result = (
            sb.table("chat_messages")
            .select("id, file_url")
            .eq("msg_type", 2)
            .gte("sent_at", "2025-10-01T00:00:00+00:00")
            .or_("content.is.null,content.eq.")
            .neq("file_url", "")
            .not_.is_("file_url", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return rows


# ── 调百炼识别单张图 ─────────────────────────────────
def recognize_image(file_url: str) -> str:
    """调 qwen-vl-plus，返回识别文本，出错返回空字符串"""
    try:
        resp = vl_client.chat.completions.create(
            model=VL_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": file_url}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
            max_tokens=100,
        )
        text = resp.choices[0].message.content.strip()
        return text
    except Exception as e:
        log.warning("识别失败 url=%s err=%s", file_url, e)
        return ""


# ── 主流程 ────────────────────────────────────────────
def main():
    rows = fetch_pending_images()
    total = len(rows)
    log.info("待识别图片: %d 条", total)
    if total == 0:
        return

    ok, fail = 0, 0
    for i, row in enumerate(rows, 1):
        rid = row["id"]
        url = row["file_url"]

        text = recognize_image(url)
        if text:
            content = f"[图片识别]{text}"
            sb.table("chat_messages").update({"content": content}).eq("id", rid).execute()
            ok += 1
            log.info("[%d/%d] OK  id=%s => %s", i, total, rid, content)
        else:
            fail += 1
            log.warning("[%d/%d] FAIL id=%s url=%s", i, total, rid, url)

        # 百炼 API 限流保护：间隔 1 秒
        if i < total:
            time.sleep(1)

    log.info("完成: 成功=%d 失败=%d 总计=%d", ok, fail, total)


if __name__ == "__main__":
    main()
