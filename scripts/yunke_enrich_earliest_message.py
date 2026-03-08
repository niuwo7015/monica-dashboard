#!/usr/bin/env python3
"""
S-005补充: 计算每个联系人的最早消息时间
- 前置条件：sql/s005_earliest_message.sql 已在Supabase Dashboard执行
- 调用 update_contacts_earliest_message() RPC 函数更新contacts表
- 输出统计：多少客户有完整记录（earliest < 2025-10-01）

也可在SQL未执行前运行 --analyze-only 模式，仅输出分析到JSON文件
"""

import os
import sys
import json
import logging
from datetime import datetime
from collections import defaultdict

from supabase import create_client

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

COMPLETENESS_CUTOFF = '2025-10-01T00:00:00+00:00'


def try_rpc_update():
    """尝试调用RPC函数更新earliest_message_at"""
    try:
        result = supabase.rpc('update_contacts_earliest_message', {}).execute()
        if result.data:
            count = result.data[0]['updated_count'] if result.data else 0
            logger.info(f"RPC更新成功：{count}个联系人已标记earliest_message_at")
            return True, count
        return True, 0
    except Exception as e:
        logger.warning(f"RPC函数不可用（需先执行SQL迁移）: {e}")
        return False, 0


def analyze_earliest_messages():
    """纯Python分析：遍历contacts，查每个人的最早消息"""
    logger.info("开始纯Python分析模式...")

    # 获取所有联系人
    all_contacts = []
    offset = 0
    page_size = 1000
    while True:
        result = supabase.table('contacts').select(
            'id, wechat_id, sales_wechat_id, nickname, remark, friend_type'
        ).neq('friend_type', 2).range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_contacts.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    logger.info(f"共获取 {len(all_contacts)} 个联系人（排除群聊）")

    # 逐个查最早消息
    results = {}
    complete_count = 0
    incomplete_count = 0
    no_message_count = 0

    for i, contact in enumerate(all_contacts):
        wxid = contact['wechat_id']

        if wxid in results:
            # 同一微信号在多个销售下，复用结果
            earliest = results[wxid]
        else:
            try:
                r = supabase.table('chat_messages').select('sent_at').eq(
                    'wechat_id', wxid
                ).is_('room_id', 'null').order('sent_at', desc=False).limit(1).execute()

                if r.data and r.data[0].get('sent_at'):
                    earliest = r.data[0]['sent_at']
                else:
                    earliest = None
            except Exception:
                earliest = None

            results[wxid] = earliest

        if earliest is None:
            no_message_count += 1
        elif earliest < COMPLETENESS_CUTOFF:
            complete_count += 1
        else:
            incomplete_count += 1

        if (i + 1) % 500 == 0:
            logger.info(f"  进度: {i+1}/{len(all_contacts)}, "
                       f"完整{complete_count}, 不完整{incomplete_count}, 无消息{no_message_count}")

    logger.info(f"\n分析完成:")
    logger.info(f"  总联系人: {len(all_contacts)}")
    logger.info(f"  有完整记录 (earliest < 2025-10-01): {complete_count}")
    logger.info(f"  记录不完整 (earliest >= 2025-10-01): {incomplete_count}")
    logger.info(f"  无消息记录: {no_message_count}")

    # 保存分析结果
    output = {
        'analyzed_at': datetime.now().isoformat(),
        'completeness_cutoff': COMPLETENESS_CUTOFF,
        'total_contacts': len(all_contacts),
        'complete_records': complete_count,
        'incomplete_records': incomplete_count,
        'no_messages': no_message_count,
        'earliest_per_wechat': {k: v for k, v in results.items() if v is not None},
    }

    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.s005_earliest_analysis.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"分析结果已保存: {output_file}")

    return output


def report_completeness():
    """从已更新的contacts表统计完整性"""
    try:
        # 有earliest_message_at的联系人
        r_complete = supabase.table('contacts').select(
            'id', count='exact'
        ).neq('friend_type', 2).lt(
            'earliest_message_at', '2025-10-01'
        ).execute()

        r_incomplete = supabase.table('contacts').select(
            'id', count='exact'
        ).neq('friend_type', 2).gte(
            'earliest_message_at', '2025-10-01'
        ).execute()

        r_null = supabase.table('contacts').select(
            'id', count='exact'
        ).neq('friend_type', 2).is_(
            'earliest_message_at', 'null'
        ).execute()

        logger.info(f"\ncontacts表完整性统计:")
        logger.info(f"  完整记录 (earliest < 2025-10-01): {r_complete.count}")
        logger.info(f"  不完整 (earliest >= 2025-10-01): {r_incomplete.count}")
        logger.info(f"  无消息: {r_null.count}")
        return True
    except Exception as e:
        logger.warning(f"统计失败（earliest_message_at字段可能还不存在）: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("S-005补充: earliest_message_at enrichment")
    logger.info("=" * 60)

    analyze_only = '--analyze-only' in sys.argv

    if not analyze_only:
        # 尝试RPC更新
        rpc_ok, count = try_rpc_update()

        if rpc_ok:
            logger.info("RPC更新成功，查看统计...")
            report_completeness()
            return

        logger.info("RPC不可用，切换到纯Python分析模式")

    # 纯Python分析
    analyze_earliest_messages()


if __name__ == '__main__':
    main()
