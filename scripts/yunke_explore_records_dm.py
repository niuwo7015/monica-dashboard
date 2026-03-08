#!/usr/bin/env python3
"""
S-005: 验证records接口私聊回补能力
- 从contacts表取几个已知有聊天记录的好友
- 用records接口传friendWechatId=好友微信号（而非群ID）
- 检查是否返回私聊消息
- 对比allRecords已有的消息数量

调用间隔 ≥ 8秒，单次验证不会大量调用。
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

SALES_WECHAT_MAP = {
    'wxid_am3kdib9tt3722': {'name': '可欣(乐乐)', 'email': 'kexin@test.com'},
    'wxid_p03xoj66oss112': {'name': '小杰(jay)', 'email': 'xiaojie@test.com'},
    'wxid_cbk7hkyyp11t12': {'name': '霄剑(Chen)', 'email': 'xiaojian@test.com'},
}


def make_sign(timestamp_ms):
    raw = f"{SIGN_KEY}{COMPANY}{PARTNER_ID}{timestamp_ms}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def yunke_api_call(path, body):
    """通用云客API调用"""
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
            # 返回完整response以便分析
            return data
        except Exception as e:
            logger.error(f"API请求失败 {path} (retry {retry+1}/3): {e}")
            if retry < 2:
                time.sleep(10)
    return None


def find_test_friends():
    """从contacts表取每个销售2个好友做测试"""
    test_friends = []

    for sales_wxid in SALES_WECHAT_MAP:
        try:
            contacts = supabase.table('contacts').select(
                'wechat_id, nickname, remark'
            ).eq(
                'sales_wechat_id', sales_wxid
            ).neq(
                'friend_type', 2
            ).limit(2).execute()

            if contacts.data:
                for c in contacts.data:
                    test_friends.append({
                        'friend_wxid': c['wechat_id'],
                        'sales_wxid': sales_wxid,
                        'name': c.get('remark') or c.get('nickname') or c['wechat_id'],
                    })
        except Exception as e:
            logger.warning(f"查询好友失败 {sales_wxid}: {e}")

    return test_friends


def count_existing_dm_messages(friend_wxid, sales_wxid):
    """统计数据库中该好友的私聊消息数"""
    try:
        # 查sales_id
        sales_info = SALES_WECHAT_MAP.get(sales_wxid, {})
        email = sales_info.get('email')
        if not email:
            return 0

        result = supabase.table('chat_messages').select(
            'id', count='exact'
        ).eq(
            'wechat_id', friend_wxid
        ).is_(
            'room_id', 'null'
        ).execute()

        return result.count or 0
    except Exception as e:
        logger.warning(f"统计消息数失败: {e}")
        return 0


def test_records_with_friend(friend_wxid, sales_wxid, friend_name):
    """核心测试：用records接口传友人微信号，看能否拉到私聊"""
    logger.info(f"\n{'='*60}")
    logger.info(f"测试: records接口 + friendWechatId={friend_wxid}")
    logger.info(f"好友: {friend_name}, 销售: {sales_wxid}")
    logger.info(f"{'='*60}")

    # 测试1: 不带时间范围
    logger.info("\n--- 测试1: 不带时间范围 ---")
    body1 = {
        'friendWechatId': friend_wxid,
        'wechatId': sales_wxid,
        'userId': PARTNER_ID,
    }
    resp1 = yunke_api_call('/open/wechat/records', body1)
    time.sleep(10)

    if resp1:
        logger.info(f"响应码: code={resp1.get('code')}, message={resp1.get('message')}")
        data1 = resp1.get('data', {})
        if isinstance(data1, dict):
            msgs1 = data1.get('messages', [])
            has_next = data1.get('hasNext', False)
            end_cursor = data1.get('end')
            logger.info(f"返回消息数: {len(msgs1)}, hasNext: {has_next}, end: {end_cursor}")

            if msgs1:
                logger.info("✅ records接口支持私聊！返回了消息")
                # 打印前3条消息样本
                for j, msg in enumerate(msgs1[:3]):
                    logger.info(f"  样本{j+1}: talker={msg.get('talker')}, "
                               f"mine={msg.get('mine')}, type={msg.get('type')}, "
                               f"text={str(msg.get('text', ''))[:50]}, "
                               f"timestamp={msg.get('timestamp')}, "
                               f"msgSvrId={msg.get('msgSvrId')}")
                return True, len(msgs1), resp1
            else:
                logger.info("❌ 返回空消息列表")
        else:
            logger.info(f"data类型异常: {type(data1)}, 内容: {str(data1)[:200]}")
    else:
        logger.info("❌ API调用失败，无响应")

    # 测试2: 带时间范围（最近7天）
    logger.info("\n--- 测试2: 带startDate/endDate（最近7天） ---")
    now = datetime.now()
    start_date = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    end_date = now.strftime('%Y-%m-%d %H:%M:%S')
    body2 = {
        'friendWechatId': friend_wxid,
        'wechatId': sales_wxid,
        'userId': PARTNER_ID,
        'startDate': start_date,
        'endDate': end_date,
    }
    resp2 = yunke_api_call('/open/wechat/records', body2)
    time.sleep(10)

    if resp2:
        logger.info(f"响应码: code={resp2.get('code')}, message={resp2.get('message')}")
        data2 = resp2.get('data', {})
        if isinstance(data2, dict):
            msgs2 = data2.get('messages', [])
            logger.info(f"返回消息数: {len(msgs2)}")
            if msgs2:
                logger.info("✅ records接口(带日期)支持私聊！")
                for j, msg in enumerate(msgs2[:3]):
                    logger.info(f"  样本{j+1}: talker={msg.get('talker')}, "
                               f"mine={msg.get('mine')}, type={msg.get('type')}, "
                               f"text={str(msg.get('text', ''))[:50]}")
                return True, len(msgs2), resp2

    # 测试3: 带秒级时间戳（backfill脚本用的方式）
    logger.info("\n--- 测试3: 带start/end（秒级时间戳） ---")
    start_sec = int((now - timedelta(days=30)).timestamp())
    end_sec = int(now.timestamp())
    body3 = {
        'friendWechatId': friend_wxid,
        'wechatId': sales_wxid,
        'userId': PARTNER_ID,
        'start': start_sec,
        'end': end_sec,
    }
    resp3 = yunke_api_call('/open/wechat/records', body3)
    time.sleep(10)

    if resp3:
        logger.info(f"响应码: code={resp3.get('code')}, message={resp3.get('message')}")
        data3 = resp3.get('data', {})
        if isinstance(data3, dict):
            msgs3 = data3.get('messages', [])
            logger.info(f"返回消息数: {len(msgs3)}")
            if msgs3:
                logger.info("✅ records接口(秒级时间戳)支持私聊！")
                for j, msg in enumerate(msgs3[:3]):
                    logger.info(f"  样本{j+1}: talker={msg.get('talker')}, "
                               f"mine={msg.get('mine')}, type={msg.get('type')}, "
                               f"text={str(msg.get('text', ''))[:50]}")
                return True, len(msgs3), resp3

    return False, 0, resp1 or resp2 or resp3


def main():
    logger.info("=" * 60)
    logger.info("S-005: 验证records接口私聊回补能力")
    logger.info("=" * 60)

    # Step 1: 找测试好友
    logger.info("\n[Step 1] 从数据库获取测试好友...")
    test_friends = find_test_friends()

    if not test_friends:
        logger.error("找不到测试好友，从contacts表直接取")
        # 兜底：直接取几个contacts
        result = supabase.table('contacts').select(
            'wechat_id, sales_wechat_id, nickname, remark'
        ).neq('friend_type', 2).limit(6).execute()
        if result.data:
            for c in result.data:
                if c['sales_wechat_id'] in SALES_WECHAT_MAP:
                    test_friends.append({
                        'friend_wxid': c['wechat_id'],
                        'sales_wxid': c['sales_wechat_id'],
                        'name': c.get('remark') or c.get('nickname') or c['wechat_id'],
                    })

    logger.info(f"共找到 {len(test_friends)} 个测试好友")
    for tf in test_friends:
        logger.info(f"  - {tf['name']} ({tf['friend_wxid']}) → 销售 {tf['sales_wxid']}")

    # Step 2: 逐个测试records接口
    logger.info("\n[Step 2] 逐个测试records接口...")
    results = []

    # 只测前3个好友（节省API调用）
    for i, tf in enumerate(test_friends[:3]):
        existing_count = count_existing_dm_messages(tf['friend_wxid'], tf['sales_wxid'])
        logger.info(f"\n数据库中该好友已有私聊消息: {existing_count}条")

        success, msg_count, raw_resp = test_records_with_friend(
            tf['friend_wxid'], tf['sales_wxid'], tf['name']
        )

        results.append({
            'friend': tf['name'],
            'friend_wxid': tf['friend_wxid'],
            'sales_wxid': tf['sales_wxid'],
            'success': success,
            'records_count': msg_count,
            'existing_db_count': existing_count,
        })

        if i < len(test_friends[:3]) - 1:
            logger.info("等待10秒后测试下一个好友...")
            time.sleep(10)

    # Step 3: 汇总结论
    logger.info("\n" + "=" * 60)
    logger.info("S-005 验证结果汇总")
    logger.info("=" * 60)

    success_count = sum(1 for r in results if r['success'])
    logger.info(f"测试好友数: {len(results)}")
    logger.info(f"成功返回私聊消息: {success_count}/{len(results)}")

    for r in results:
        status = "✅ 成功" if r['success'] else "❌ 失败"
        logger.info(
            f"  {status} | {r['friend']} ({r['friend_wxid']}) "
            f"| records返回: {r['records_count']}条 "
            f"| 数据库已有: {r['existing_db_count']}条"
        )

    if success_count > 0:
        logger.info("\n🎉 结论: records接口支持私聊！可以用于回补私聊历史记录。")
        logger.info("下一步: 编写全量私聊回补脚本。")
    else:
        logger.info("\n💔 结论: records接口不支持私聊，需要继续用allRecords方式。")

    # 输出JSON结果供后续分析
    result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.s005_explore_result.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"\n详细结果已保存到: {result_file}")


if __name__ == '__main__':
    main()
