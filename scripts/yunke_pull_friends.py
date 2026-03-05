#!/usr/bin/env python3
"""
云客好友列表同步脚本
- 遍历所有销售微信号，拉取好友列表
- 1:1映射写入contacts表
- 用(wechat_id, sales_wechat_id)做upsert
"""

import os
import sys
import time
import hashlib
import json
import logging
from datetime import datetime

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

# ============ 销售微信号列表 ============
SALES_WECHAT_IDS = [
    'wxid_am3kdib9tt3722',   # 可欣(乐乐)
    'wxid_p03xoj66oss112',   # 小杰(jay)
    'wxid_cbk7hkyyp11t12',   # 霄剑(Chen)
    'wxid_aufah51bw9ok22',   # Fiona
    'wxid_idjldooyihpj22',   # 晴天喵
    'wxid_rxc39paqvic522',   # Joy
]


def make_sign(timestamp_ms):
    """生成云客API签名"""
    raw = f"{SIGN_KEY}{COMPANY}{PARTNER_ID}{timestamp_ms}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def pull_friends_page(wechat_id, page_timestamp="0"):
    """拉取一页好友列表"""
    timestamp_ms = str(int(time.time() * 1000))
    sign = make_sign(timestamp_ms)

    headers = {
        'partnerId': PARTNER_ID,
        'company': COMPANY,
        'timestamp': timestamp_ms,
        'sign': sign,
        'Content-Type': 'application/json'
    }

    body = {
        'wechatId': wechat_id,
        'userId': PARTNER_ID,
        'timestamp': page_timestamp,
    }

    url = f"{API_BASE}/open/wechat/friends"

    for retry in range(3):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # API may return {code: 0/200, data: ...} or {success: true, data: ...}
            is_success = data.get('code') in (0, 200) or data.get('success') is True
            if not is_success:
                logger.warning(f"API返回错误: {data}")
                if retry < 2:
                    time.sleep(10)
                    continue
                return None

            return data.get('data', {})
        except Exception as e:
            logger.error(f"API请求失败 (retry {retry+1}/3): {e}")
            if retry < 2:
                time.sleep(10)
    return None


def timestamp_to_iso(ts):
    """时间戳转ISO格式（支持毫秒和秒级时间戳）"""
    if not ts:
        return None
    try:
        ts_val = int(ts)
        if ts_val > 1e12:  # 毫秒
            ts_val = ts_val / 1000
        if ts_val > 0:
            return datetime.fromtimestamp(ts_val).isoformat()
    except (ValueError, TypeError, OSError):
        pass
    return None


def sync_friends_for_sales(wechat_id):
    """同步一个销售的全部好友"""
    logger.info(f"开始同步: {wechat_id}")

    total = 0
    new_count = 0
    update_count = 0
    deleted_count = 0
    page_timestamp = "0"

    while True:
        data = pull_friends_page(wechat_id, page_timestamp)
        if data is None:
            logger.error(f"拉取好友失败: {wechat_id}")
            break

        friends = data.get('friends', data.get('list', []))
        if not friends:
            break

        for friend in friends:
            total += 1
            friend_wechat_id = friend.get('wechatId', '')
            if not friend_wechat_id:
                continue

            is_deleted = 1 if friend.get('delete') == 1 else 0
            if is_deleted:
                deleted_count += 1

            row = {
                'wechat_id': friend_wechat_id,
                'wechat_alias': friend.get('alias'),
                'nickname': friend.get('nickname'),
                'remark': friend.get('remark'),
                'friend_type': friend.get('type', 1),
                'from_type': friend.get('fromType'),
                'head_url': friend.get('headUrl'),
                'phone': friend.get('phone'),
                'description': friend.get('description'),
                'gender': friend.get('gender', 0),
                'region': friend.get('region'),
                'yunke_create_time': timestamp_to_iso(friend.get('createTime')),
                'add_time': timestamp_to_iso(friend.get('addTime')),
                'sales_wechat_id': wechat_id,
                'is_deleted': is_deleted,
                'yunke_update_time': timestamp_to_iso(friend.get('updateTime')),
                'updated_at': datetime.now().isoformat(),
            }

            # 清理None值
            row = {k: v for k, v in row.items() if v is not None}

            try:
                # 先查是否存在
                existing = supabase.table('contacts').select('id').eq(
                    'wechat_id', friend_wechat_id
                ).eq('sales_wechat_id', wechat_id).execute()

                if existing.data:
                    # 更新
                    supabase.table('contacts').update(row).eq(
                        'wechat_id', friend_wechat_id
                    ).eq('sales_wechat_id', wechat_id).execute()
                    update_count += 1
                else:
                    # 新增
                    row['created_at'] = datetime.now().isoformat()
                    supabase.table('contacts').insert(row).execute()
                    new_count += 1
            except Exception as e:
                logger.warning(f"写入contacts失败 wechat_id={friend_wechat_id}: {e}")

        # 检查分页
        end_ts = data.get('end', '0')
        if end_ts and str(end_ts) != '0' and str(end_ts) != page_timestamp:
            page_timestamp = str(end_ts)
        else:
            break

        time.sleep(2)

    logger.info(
        f"  {wechat_id}: 总好友{total}, 新增{new_count}, "
        f"更新{update_count}, 已删除{deleted_count}"
    )
    return total, new_count, update_count, deleted_count


def main():
    logger.info("=" * 50)
    logger.info("开始同步云客好友列表")

    grand_total = 0
    grand_new = 0
    grand_update = 0
    grand_deleted = 0

    for wechat_id in SALES_WECHAT_IDS:
        total, new_c, update_c, deleted_c = sync_friends_for_sales(wechat_id)
        grand_total += total
        grand_new += new_c
        grand_update += update_c
        grand_deleted += deleted_c
        time.sleep(3)

    logger.info(f"同步完成: 总{grand_total}, 新增{grand_new}, 更新{grand_update}, 已删除{grand_deleted}")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
