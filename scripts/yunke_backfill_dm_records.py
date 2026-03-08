#!/usr/bin/env python3
"""
S-005: 用records接口回补私聊历史记录
- S-005验证：records接口传friendWechatId=好友微信号可拉取私聊记录
- 遍历contacts表所有好友，逐个用records接口拉取完整私聊历史
- 批量upsert到chat_messages，用msg_svr_id去重
- 调用间隔 ≥ 10秒，限流时sleep(60)

优势（对比allRecords）：
- allRecords按时间窗口扫描，大量空窗口浪费API调用
- records按好友维度拉取，直接获取该好友全部消息，效率高得多
- 实测发现allRecords未覆盖到的消息，records可以拉到
"""

import os
import sys
import time
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from supabase import create_client

# ============ 配置 ============
COMPANY = os.getenv('YUNKE_COMPANY', '5fri8k')
PARTNER_ID = os.getenv('YUNKE_PARTNER_ID', 'pDB33ABE148934DD081FD7D4C80654195')
SIGN_KEY = os.getenv('YUNKE_SIGN_KEY', 'F446226EBF084CF6AAC00E')
API_BASE = os.getenv('YUNKE_API_BASE', 'https://phone.yunkecn.com')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_ROLE_KEY 环境变量未设置")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============ 销售微信号映射 ============
SALES_WECHAT_MAP = {
    'wxid_am3kdib9tt3722': {'name': '可欣(乐乐)', 'email': 'kexin@test.com'},
    'wxid_p03xoj66oss112': {'name': '小杰(jay)', 'email': 'xiaojie@test.com'},
    'wxid_cbk7hkyyp11t12': {'name': '霄剑(Chen)', 'email': 'xiaojian@test.com'},
    'wxid_aufah51bw9ok22': {'name': 'Fiona', 'email': None},
    'wxid_idjldooyihpj22': {'name': '晴天喵', 'email': None},
    'wxid_rxc39paqvic522': {'name': 'Joy', 'email': None},
}

_sales_id_cache = {}

# ============ 进度状态文件 ============
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '.s005_backfill_progress.json')


def load_progress():
    """加载回补进度"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {'completed_friends': [], 'stats': {'total_pulled': 0, 'total_inserted': 0, 'total_skipped': 0}}


def save_progress(progress):
    """保存回补进度"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(progress, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def get_sales_id(wechat_id):
    info = SALES_WECHAT_MAP.get(wechat_id)
    if not info or not info['email']:
        return None
    email = info['email']
    if email in _sales_id_cache:
        return _sales_id_cache[email]
    try:
        result = supabase.table('users').select('id').eq('email', email).execute()
        if result.data:
            _sales_id_cache[email] = result.data[0]['id']
            return _sales_id_cache[email]
    except Exception as e:
        logger.warning(f"查询sales_id失败 email={email}: {e}")
    return None


def get_customer_id(wechat_id, sales_wechat_id):
    try:
        result = supabase.table('contacts').select('customer_id').eq(
            'wechat_id', wechat_id
        ).eq('sales_wechat_id', sales_wechat_id).execute()
        if result.data and result.data[0].get('customer_id'):
            return result.data[0]['customer_id']
    except Exception:
        pass
    return None


def make_sign(timestamp_ms):
    raw = f"{SIGN_KEY}{COMPANY}{PARTNER_ID}{timestamp_ms}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def yunke_api_call(path, body):
    """通用云客API调用，返回 dict | 'RATE_LIMITED'"""
    timestamp_ms = str(int(time.time() * 1000))
    sign = make_sign(timestamp_ms)
    headers = {
        'partnerId': PARTNER_ID,
        'company': COMPANY,
        'timestamp': timestamp_ms,
        'sign': sign,
        'Content-Type': 'application/json'
    }
    for retry in range(3):
        try:
            resp = requests.post(f"{API_BASE}{path}", json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            is_success = data.get('code') in (0, 200) or data.get('success') is True
            if not is_success:
                msg = str(data.get('message', ''))
                logger.warning(f"API返回错误 {path}: {msg}")
                if '频繁' in msg:
                    if retry < 2:
                        logger.info(f"被限流，等待30秒后重试 ({retry+1}/3)")
                        time.sleep(30)
                        continue
                    return 'RATE_LIMITED'
                else:
                    if retry < 2:
                        time.sleep(10)
                        continue
                    return 'RATE_LIMITED'
            return data.get('data', {})
        except Exception as e:
            logger.error(f"API请求失败 {path} (retry {retry+1}/3): {e}")
            if retry < 2:
                time.sleep(10)
    return 'RATE_LIMITED'


def timestamp_ms_to_iso(ts_ms):
    if not ts_ms:
        return None
    try:
        ts_sec = int(ts_ms) / 1000
        return datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    except (ValueError, TypeError, OSError):
        return None


def batch_upsert(rows, batch_size=50):
    """批量upsert到chat_messages"""
    if not rows:
        return 0, 0
    inserted = 0
    skipped = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            supabase.table('chat_messages').upsert(
                batch, on_conflict='msg_svr_id'
            ).execute()
            inserted += len(batch)
        except Exception as e:
            logger.warning(f"批量写入失败({len(batch)}条): {e}，回退逐条写入")
            for row in batch:
                try:
                    supabase.table('chat_messages').upsert(
                        row, on_conflict='msg_svr_id'
                    ).execute()
                    inserted += 1
                except Exception as e2:
                    logger.warning(f"写入失败 msg_svr_id={row.get('msg_svr_id')}: {e2}")
                    skipped += 1
    return inserted, skipped


def pull_friend_dm_records(friend_wxid, sales_wxid):
    """用records接口拉取一个好友的全部私聊记录（带分页）"""
    all_msgs = []
    body = {
        'friendWechatId': friend_wxid,
        'wechatId': sales_wxid,
        'userId': PARTNER_ID,
    }

    rounds = 0
    rate_limit_count = 0

    while rounds < 200:  # 安全上限
        rounds += 1
        data = yunke_api_call('/open/wechat/records', body)
        time.sleep(10)  # 严格10秒间隔

        if data == 'RATE_LIMITED':
            rate_limit_count += 1
            if rate_limit_count >= 3:
                logger.warning(f"好友 {friend_wxid} 连续{rate_limit_count}次限流，跳过")
                break
            logger.warning(f"被限流，等待60秒后重试")
            time.sleep(60)
            continue

        rate_limit_count = 0  # 重置

        if not data:
            break

        msgs = data.get('messages', [])
        all_msgs.extend(msgs)

        if not data.get('hasNext') or not msgs:
            break

        body['start'] = data.get('end')

    return all_msgs


def process_dm_records(records, friend_wxid, sales_wxid):
    """处理records接口返回的私聊消息"""
    if not records:
        return 0, 0

    rows = []
    skipped = 0
    sales_id = get_sales_id(sales_wxid)
    customer_id = get_customer_id(friend_wxid, sales_wxid)

    for record in records:
        msg_svr_id = record.get('msgSvrId')
        if not msg_svr_id:
            skipped += 1
            continue

        is_mine = record.get('mine', False)
        sender_type = 'sales' if is_mine else 'customer'
        talker = record.get('talker', '')

        row = {
            'msg_svr_id': str(msg_svr_id),
            'wechat_id': friend_wxid,  # 私聊: wechat_id=对方好友ID
            'sender_type': sender_type,
            'content': record.get('text', ''),
            'msg_type': str(record.get('type', '')),
            'sent_at': timestamp_ms_to_iso(record.get('timestamp')),
            'file_url': record.get('file', ''),
            'room_id': None,  # 私聊没有room_id
        }

        if sales_id:
            row['sales_id'] = sales_id
        if customer_id:
            row['customer_id'] = customer_id

        for k, v in row.items():
            if v == '':
                row[k] = None

        rows.append(row)

    inserted, write_skipped = batch_upsert(rows)
    return inserted, skipped + write_skipped


def get_all_friends():
    """从contacts表获取所有好友（排除群聊）"""
    all_friends = []
    for sales_wxid in SALES_WECHAT_MAP:
        offset = 0
        page_size = 1000
        while True:
            try:
                result = supabase.table('contacts').select(
                    'wechat_id, nickname, remark'
                ).eq(
                    'sales_wechat_id', sales_wxid
                ).neq(
                    'friend_type', 2  # 排除群聊
                ).range(offset, offset + page_size - 1).execute()

                if not result.data:
                    break

                for c in result.data:
                    wxid = c.get('wechat_id', '')
                    if wxid and '@chatroom' not in wxid:
                        all_friends.append({
                            'friend_wxid': wxid,
                            'sales_wxid': sales_wxid,
                            'name': c.get('remark') or c.get('nickname') or wxid,
                        })

                if len(result.data) < page_size:
                    break
                offset += page_size
            except Exception as e:
                logger.warning(f"查询contacts失败 {sales_wxid} offset={offset}: {e}")
                break

    logger.info(f"共获取 {len(all_friends)} 个好友")

    # 按销售分组统计
    sales_counts = {}
    for f in all_friends:
        sales_counts[f['sales_wxid']] = sales_counts.get(f['sales_wxid'], 0) + 1
    for wxid, count in sales_counts.items():
        name = SALES_WECHAT_MAP[wxid]['name']
        logger.info(f"  {name}: {count}个好友")

    return all_friends


def main():
    logger.info("=" * 60)
    logger.info("S-005: records接口私聊历史回补")
    logger.info("=" * 60)

    # 加载进度
    progress = load_progress()
    completed = set(progress['completed_friends'])
    stats = progress['stats']

    logger.info(f"已完成: {len(completed)}个好友")
    logger.info(f"累计统计: 拉取{stats['total_pulled']}, 写入{stats['total_inserted']}, 跳过{stats['total_skipped']}")

    # 获取所有好友
    all_friends = get_all_friends()

    # 过滤已完成的
    remaining = [f for f in all_friends
                 if f'{f["sales_wxid"]}:{f["friend_wxid"]}' not in completed]
    logger.info(f"剩余需处理: {len(remaining)}个好友")

    if not remaining:
        logger.info("所有好友已处理完毕！")
        return

    # 逐个好友拉取
    processed = 0
    session_pulled = 0
    session_inserted = 0
    session_skipped = 0
    empty_count = 0

    for i, friend in enumerate(remaining):
        friend_key = f'{friend["sales_wxid"]}:{friend["friend_wxid"]}'

        # 拉取消息
        msgs = pull_friend_dm_records(friend['friend_wxid'], friend['sales_wxid'])

        if msgs:
            inserted, skipped = process_dm_records(msgs, friend['friend_wxid'], friend['sales_wxid'])
            session_pulled += len(msgs)
            session_inserted += inserted
            session_skipped += skipped
            empty_count = 0

            logger.info(
                f"[{i+1}/{len(remaining)}] {friend['name']} ({friend['friend_wxid']}): "
                f"拉取{len(msgs)}条, 写入{inserted}条"
            )
        else:
            empty_count += 1
            if (i + 1) % 50 == 0 or empty_count == 1:
                logger.info(
                    f"[{i+1}/{len(remaining)}] {friend['name']}: 无消息 (连续空{empty_count})"
                )

        # 标记完成
        completed.add(friend_key)
        processed += 1

        # 每处理10个好友保存一次进度
        if processed % 10 == 0:
            progress['completed_friends'] = list(completed)
            progress['stats']['total_pulled'] = stats['total_pulled'] + session_pulled
            progress['stats']['total_inserted'] = stats['total_inserted'] + session_inserted
            progress['stats']['total_skipped'] = stats['total_skipped'] + session_skipped
            save_progress(progress)

            if processed % 100 == 0:
                logger.info(
                    f"--- 进度保存 [{processed}/{len(remaining)}] ---\n"
                    f"    本轮: 拉取{session_pulled}, 写入{session_inserted}\n"
                    f"    累计: 完成{len(completed)}个好友"
                )

    # 最终保存
    progress['completed_friends'] = list(completed)
    progress['stats']['total_pulled'] = stats['total_pulled'] + session_pulled
    progress['stats']['total_inserted'] = stats['total_inserted'] + session_inserted
    progress['stats']['total_skipped'] = stats['total_skipped'] + session_skipped
    save_progress(progress)

    logger.info("\n" + "=" * 60)
    logger.info("S-005 私聊回补完成!")
    logger.info(f"本轮处理: {processed}个好友")
    logger.info(f"本轮拉取: {session_pulled}条, 写入: {session_inserted}条, 跳过: {session_skipped}条")
    logger.info(f"总计完成: {len(completed)}个好友")
    logger.info(f"总计拉取: {progress['stats']['total_pulled']}条")
    logger.info(f"总计写入: {progress['stats']['total_inserted']}条")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
