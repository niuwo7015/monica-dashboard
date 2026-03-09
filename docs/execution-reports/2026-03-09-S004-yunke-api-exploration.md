# S-004: 云客API探索 — 最终报告

> 日期：2026-03-09
> 状态：探索完成，回补路径已确认

---

## 核心结论

**records接口支持按个人好友wxid拉取历史聊天记录，回补可行。**

但有限制：只返回文本(type=1)和语音(type=34)消息，不返回图片/视频/文件。

---

## 发现汇总

### 1. records 支持个人好友 (已验证)

- `friendWechatId` 支持个人wxid（不只是群@chatroom）
- start/end 必须是**日期字符串** `"yyyy-MM-dd HH:mm:ss"`，不是整数时间戳
- 整数时间戳会报 "时间格式有误"
- 时间范围模式限流 ≥ 2秒/次，最大跨度3天
- 实测：`wxid_fnhtmw98ndt712` 最近3天返回1条文本消息

### 2. getAllFriendsIncrement (正确端点)

- 端点是 `/open/wechat/getAllFriendsIncrement`，不是 `/getAllFriends`
- 旧端点 `/getAllFriends` 返回 "缺少参数"
- 参数: `wechatId`, `type`, `getFirstData`, `queryMode`, `startTime`(日期字符串)
- 返回 `lastChatTime`（毫秒时间戳），可用于筛选活跃好友
- 实测：queryMode=updateTime 最近7天返回173条好友记录

### 3. getRecordsByMsgId 参数修正

- `msgSvrIds` 是**逗号分隔字符串**，不是JSON数组
- 错误: `["id1", "id2"]` → 正确: `"id1,id2"`
- 不带wechatId限流60s，带wechatId限流30s
- 用途：补充allRecords中延迟的文件URL

### 4. API响应格式

- 响应没有 `code` 字段，直接是 `{message: "success", data: {...}}`
- 成功标识：`message` 为 "success" 或 "查询成功"

---

## 已发现的代码BUG

| 文件 | BUG | 正确做法 |
|------|-----|---------|
| `yunke_backfill.py` | records start/end传整数时间戳 | 改为日期字符串 `"yyyy-MM-dd HH:mm:ss"` |
| `yunke_backfill_dm_records.py` | 同上（如果使用records的start/end） | 改为日期字符串 |

---

## 回补可行性分析

### 方案：records按好友逐个回补

| 项目 | 值 |
|------|---|
| 可回补内容 | 文本 + 语音（占最有价值的分析数据） |
| 不可回补 | 图片、视频、文件、表情、链接 |
| 时间跨度 | 最多6个月（数据保留期限制） |
| 回补起始日 | 2025-09-09（6个月前） |
| 总天数 | ~180天 |
| 每好友窗口数 | 60个（3天/窗口） |
| 限流 | ≥ 2秒/次 |

### 耗时估算

| 活跃好友数 | API调用次数 | 耗时(3s/call) | 耗时(5s/call) |
|-----------|-----------|--------------|--------------|
| 200 | 12,000 | 10h | 17h |
| 500 | 30,000 | 25h ≈ 1天 | 42h ≈ 1.7天 |
| 1,000 | 60,000 | 50h ≈ 2天 | 83h ≈ 3.5天 |
| 2,000 | 120,000 | 100h ≈ 4天 | 167h ≈ 7天 |

### 优化策略

1. **优先活跃好友**: 用getAllFriendsIncrement的lastChatTime筛选6个月内有聊天的好友
2. **空窗口跳跃**: 连续N个空窗口后跳过一段时间（大多数好友不是天天聊）
3. **6个销售分开跑**: 按销售账号排队，每个账号的好友列表独立
4. **游标模式备选**: 如果某好友消息量大，可用timestamp+direction游标翻页（5s限流）

### 关键风险

- **API到期**: 3月20日到期，剩余11天
- **只有文本+语音**: records不返回图片等非文本消息
- **数据保留6个月**: 2025-09-09之前的数据已过期
- **限流策略**: 必须严格控制调用间隔，被限流后sleep(60)

---

## 下一步行动

### 需要人工决策

1. **是否启动回补？** — 只有文本+语音，没有图片，是否仍有价值？
2. **回补范围？** — 全部6个月 vs 最近3个月？全部好友 vs 只要活跃好友？
3. **优先级？** — 回补 vs 其他Phase 1任务的优先级

### 如果决定回补

1. 修复 `yunke_backfill.py` 中的start/end参数格式 (整数 → 日期字符串)
2. 编写 `yunke_backfill_by_friend.py` — 按好友逐个回补脚本
3. 用 `getAllFriendsIncrement` 获取活跃好友列表(带lastChatTime)
4. 按lastChatTime排序，优先回补最近活跃的好友
5. 部署到服务器后台运行，定期检查进度

---

## 测试脚本文件

| 文件 | 说明 | 位置 |
|------|------|------|
| `yunke_explore_apis.py` | Round 1 探索（旧参数格式） | 服务器 /home/admin/monica-scripts/ |
| `yunke_explore_round2.py` | Round 2 探索（发现records支持个人好友） | 服务器 /home/admin/monica-scripts/ |
| `yunke_verify_correct_params.py` | Round 3 验证（正确参数格式） | 服务器 /home/admin/monica-scripts/ |

---

## 知识库更新

已更新 `docs/knowledge/yunke_api_full_reference.md`：
- 修正 records start/end 参数类型（整数 → 日期字符串）
- 修正 getAllFriends → getAllFriendsIncrement 端点名
- 修正 getRecordsByMsgId msgSvrIds 参数类型（数组 → 逗号分隔字符串）
- 补充 API 响应格式说明（无code字段）
- 补充 getAllFriendsIncrement 完整参数和响应格式
