#!/usr/bin/env python3
"""
T-013a: 语音消息转文字
用百炼 paraformer-v2 识别 voice (msg_type=3) 并写回 content。
用法:
  python3 transcribe_voice.py              # 处理全部待转录
  python3 transcribe_voice.py --limit 10   # 只处理10条
  python3 transcribe_voice.py --dry-run    # 只查询不执行
"""

import os, sys, json, time, logging, argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# --------------- config ---------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dieeejjzbhkpgxdhwlxf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

BATCH_SIZE = 50        # DashScope 单次最多100，保守用50
PAGE_SIZE = 1000       # Supabase 分页大小
MIN_DATE = "2025-10-01T00:00:00"

# --------------- supabase ---------------
_sb = None

def get_sb():
    global _sb
    if _sb is None:
        from supabase import create_client
        if not SUPABASE_KEY:
            log.error("SUPABASE_SERVICE_ROLE_KEY 未设置"); sys.exit(1)
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

# --------------- 查询待转录记录 ---------------
def fetch_voice_messages(limit=0):
    """msg_type=3, content为空/null, file_url非空, sent_at>=2025-10-01"""
    sb = get_sb()
    all_rows = []
    offset = 0

    while True:
        q = (sb.table("chat_messages")
             .select("msg_svr_id, file_url, sent_at")
             .eq("msg_type", 3)
             .or_("content.is.null,content.eq.")
             .neq("file_url", "")
             .gte("sent_at", MIN_DATE)
             .order("sent_at")
             .range(offset, offset + PAGE_SIZE - 1))
        result = q.execute()

        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    # 去重（同一file_url可能有多条）
    seen = set()
    unique = []
    for r in all_rows:
        if r["msg_svr_id"] not in seen:
            seen.add(r["msg_svr_id"])
            unique.append(r)

    if limit > 0:
        unique = unique[:limit]
    return unique

# --------------- DashScope 转录 ---------------
def transcribe_batch(file_urls):
    """提交一批URL到 paraformer-v2，返回 {file_url: text}"""
    import requests
    from http import HTTPStatus
    from dashscope.audio.asr import Transcription

    log.info(f"  提交 {len(file_urls)} 个文件到 paraformer-v2 ...")

    task_resp = Transcription.async_call(
        model="paraformer-v2",
        file_urls=file_urls,
        language_hints=["zh", "en"],
    )

    if task_resp.status_code != HTTPStatus.OK:
        log.error(f"  提交失败: {task_resp.status_code} - {task_resp.message}")
        return {}

    task_id = task_resp.output.task_id
    log.info(f"  task_id={task_id}, 等待识别 ...")

    result_resp = Transcription.wait(task=task_id)

    if result_resp.status_code != HTTPStatus.OK:
        log.error(f"  识别失败: {result_resp.status_code} - {result_resp.message}")
        return {}

    url_to_text = {}
    results = result_resp.output.get("results") if isinstance(result_resp.output, dict) else getattr(result_resp.output, "results", None)
    if not results:
        log.warning("  无识别结果")
        return url_to_text

    for item in results:
        furl = item.get("file_url", "")
        status = item.get("subtask_status", "")
        if status != "SUCCEEDED":
            log.warning(f"  子任务失败: status={status} url={furl[:80]}")
            continue

        trans_url = item.get("transcription_url", "")
        if not trans_url:
            continue

        try:
            resp = requests.get(trans_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            texts = []
            for t in data.get("transcripts", []):
                txt = t.get("text", "").strip()
                if txt:
                    texts.append(txt)
            full = " ".join(texts).strip()
            if full:
                url_to_text[furl] = full
        except Exception as e:
            log.warning(f"  获取转录JSON失败: {e}")

    return url_to_text

# --------------- 写回 content ---------------
def update_content(msg_svr_id, text):
    sb = get_sb()
    try:
        sb.table("chat_messages").update(
            {"content": text}
        ).eq("msg_svr_id", msg_svr_id).execute()
        return True
    except Exception as e:
        log.warning(f"  写回失败 {msg_svr_id}: {e}")
        return False

# --------------- main ---------------
def main():
    parser = argparse.ArgumentParser(description="T-013a 语音转文字")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N条(0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只查询不执行转录")
    args = parser.parse_args()

    if not DASHSCOPE_KEY:
        log.error("DASHSCOPE_API_KEY 未设置"); sys.exit(1)

    import dashscope
    dashscope.api_key = DASHSCOPE_KEY

    log.info("=" * 50)
    log.info("T-013a: 语音转文字 (paraformer-v2)")
    log.info("=" * 50)

    rows = fetch_voice_messages(limit=args.limit)
    log.info(f"待转录: {len(rows)} 条 (sent_at >= {MIN_DATE})")

    if not rows:
        log.info("无待处理记录，退出")
        return

    if args.dry_run:
        for r in rows[:20]:
            log.info(f"  {r['sent_at']} | {r['msg_svr_id']} | {r['file_url'][:80]}")
        if len(rows) > 20:
            log.info(f"  ... 省略 {len(rows)-20} 条")
        log.info("dry-run 完毕")
        return

    total_ok = 0
    total_fail = 0
    total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        bnum = i // BATCH_SIZE + 1
        log.info(f"批次 {bnum}/{total_batches}: {len(batch)} 条")

        # 建 url->msg_svr_id 映射
        url_map = {}
        urls = []
        for r in batch:
            u = r["file_url"]
            if u and u not in url_map:
                url_map[u] = r["msg_svr_id"]
                urls.append(u)

        if not urls:
            continue

        try:
            url_to_text = transcribe_batch(urls)
        except Exception as e:
            log.error(f"  批次异常: {e}")
            total_fail += len(urls)
            continue

        ok = 0
        for u, txt in url_to_text.items():
            msid = url_map.get(u)
            if msid and update_content(msid, txt):
                ok += 1
                log.info(f"    ✓ {msid}: {txt[:60]}")

        fail = len(urls) - len(url_to_text)
        total_ok += ok
        total_fail += fail
        log.info(f"  批次结果: 成功={ok}, 失败={fail}")

        if i + BATCH_SIZE < len(rows):
            time.sleep(2)

    log.info("=" * 50)
    log.info(f"完成! 成功={total_ok}, 失败={total_fail}, 总计={len(rows)}")

if __name__ == "__main__":
    main()
