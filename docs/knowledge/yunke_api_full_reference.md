# 云客API完整参考手册

> 最后更新：2026-03-09 (S-004 Round 3)
> 来源：官方文档 (crm.yunkecn.com/cms/settings/openPreView) + 实测验证

## 认证方式

- **Base URL**: `https://phone.yunkecn.com`
- **Method**: POST (所有接口)
- **Content-Type**: `application/json`

### 签名 Headers

| Header | 值 |
|--------|---|
| `partnerId` | `pDB33ABE148934DD081FD7D4C80654195` |
| `company` | `5fri8k` |
| `timestamp` | 当前毫秒时间戳 |
| `sign` | `MD5(SIGN_KEY + COMPANY + PARTNER_ID + timestamp).toUpperCase()` |

### API限制
- **API到期日: 2026-03-20**
- 数据保留: 约6个月
- 限流响应: `message` 含 "请勿频繁操作" 或 "频繁"
- 限流恢复: sleep(60)，连续5次限流后 sleep(120)
- 响应格式: `{message: "success", data: {...}}` — 没有 `code` 字段

---

## 接口1: `/open/wechat/allRecords` — 增量获取员工聊天数据

**用途**: 按公司维度增量拉取所有员工的聊天消息（私聊+群聊）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `timestamp` | long | 是 | 13位毫秒时间戳，查询该时间点往后1小时的数据 |
| `createTimestamp` | long | 否 | 辅助分页用（当1小时内数据>单页时） |

**约束**:
- timestamp 必须 < 当前时间 - 30分钟
- 每次返回1小时窗口的数据
- 返回所有消息类型（文本、图片、语音、视频、文件、链接等）

**响应 data**:
```json
{
  "messages": [...],
  "end": 1709000000000,
  "hasNext": true
}
```

**消息字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `msgSvrId` | string | 消息唯一ID |
| `mine` | bool | true=销售发送, false=客户发送 |
| `wechatId` | string | 销售微信号 |
| `talker` | string | 对方wxid（私聊=客户, 群聊=发言者） |
| `text` | string | 消息内容 |
| `type` | string | 消息类型 (1=文本, 3=图片, 34=语音, 43=视频, 47=表情, 49=链接/文件, 10000=系统) |
| `timestamp` | long | 消息时间（毫秒） |
| `file` | string | 文件URL（图片/语音/视频） |
| `roomid` | string | 群ID（群消息才有） |
| `oriTalker` | string | 原始发言者（群消息） |

**已知问题**:
- 不返回群聊中的客户文本（只有系统消息和格式消息）
- 回补历史数据时返回0条（可能受数据保留期限制）

---

## 接口2: `/open/wechat/records` — 获取指定好友/群聊天记录

**用途**: 按好友wxid或群ID拉取聊天记录
**支持**: 个人好友wxid **和** 群ID(@chatroom) 均可 (已实测验证)
**只返回**: 文本(type=1) 和 语音(type=34) 消息

### 场景1: 游标分页模式

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `friendWechatId` | string | 是 | 好友wxid 或 群ID(@chatroom) |
| `wechatId` | string | 是 | 销售微信号 |
| `userId` | string | 是 | partnerId |
| `timestamp` | long | 否 | 13位毫秒时间戳，游标起点 |
| `direction` | string | 否 | `"up"` 向前翻页 / `"down"` 向后翻页 |

**限流**: ≥ 5秒/次
**注意**: 不能只传direction不传timestamp，会报"时间参数错误"

### 场景2: 时间范围模式（回补用）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `friendWechatId` | string | 是 | 好友wxid 或 群ID(@chatroom) |
| `wechatId` | string | 是 | 销售微信号 |
| `userId` | string | 是 | partnerId |
| `start` | string | 是 | **日期字符串** `"yyyy-MM-dd HH:mm:ss"` |
| `end` | string | 是 | **日期字符串** `"yyyy-MM-dd HH:mm:ss"` |

**限流**: ≥ 2秒/次
**最大跨度**: 3天

> **BUG警告**: 旧代码(yunke_backfill.py)用整数时间戳传start/end，必须改为日期字符串！
> 错误: `{"start": 1709000000, "end": 1709259200}` → "时间格式有误"
> 正确: `{"start": "2025-12-01 00:00:00", "end": "2025-12-03 23:59:59"}`

---

## 接口3: `/open/wechat/friends` — 好友列表（分页）

**用途**: 按销售账号分页获取好友/群列表

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `wechatId` | string | 是 | 销售微信号 |
| `pageIndex` | int | 是 | 页码（从1开始） |
| `pageSize` | int | 是 | 每页数量（最大100） |
| `type` | int | 否 | 1=联系人, 2=群 |

**响应 data**:
```json
{
  "pageSize": 20,
  "pageIndex": 1,
  "totalCount": 3277,
  "pageCount": 164,
  "page": [...]
}
```

**好友字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 好友微信ID（注意不是`wechatId`！） |
| `name` | string | 昵称 |
| `alias` | string | 微信号 |
| `remark` | string | 备注名 |
| `type` | int | 1=联系人, 2=群成员 |
| `fromType` | string | 来源类型 |
| `headUrl` | string | 头像URL |
| `phone` | string | 手机号 |
| `gender` | int | 性别 (0=未知, 1=男, 2=女) |
| `region` | string | 地区 |
| `createTime` | long | 创建时间（秒级时间戳） |
| `addTime` | long | 添加时间（秒级时间戳） |
| `delete` | int | 1=已删除 |

---

## 接口4: `/open/wechat/getAllFriendsIncrement` — 增量获取好友/群

> **注意**: 端点是 `getAllFriendsIncrement`，不是 `getAllFriends`！

**用途**: 增量获取好友或群列表，支持按创建/更新时间查询
**已实测验证**: 2026-03-09

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `wechatId` | string | 是 | 销售微信号 |
| `type` | int | 是 | 1=好友, 2=群 |
| `getFirstData` | bool | 否 | 是否获取第一批数据 |
| `queryMode` | string | 否 | `"createTime"` 或 `"updateTime"` |
| `startTime` | string | 否 | **日期字符串** `"yyyy-MM-dd HH:mm:ss"` |

**特点**:
- 单次最多返回2000条
- 返回 `lastChatTime` 字段（毫秒时间戳，好友最后聊天时间）
- 翻页: 用返回的 `queryEndTime` + 1秒 作为下次的 `startTime`
- 返回 `total` 计数

**响应示例**:
```json
{
  "message": "查询成功",
  "data": {
    "total": 173,
    "data": [
      {
        "id": "wxid_xxx",
        "name": "昵称",
        "remark": "备注",
        "lastChatTime": 1767599021000,
        "type": 1,
        "createTime": "2024-07-10 15:29:15"
      }
    ]
  }
}
```

---

## 接口5: `/open/wechat/getRecordsByMsgId` — 文件补充链接

**用途**: 为allRecords返回的消息补充文件URL（图片/语音/视频/文件）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `msgSvrIds` | string | 是 | **逗号分隔字符串**，如 `"id1,id2,id3"` |
| `wechatId` | string | 否 | 销售微信号（提供可加速，限流30s vs 60s） |

**约束**:
- 单次最多100个ID
- 不带wechatId: 限流 ≥ 60秒/次
- 带wechatId: 限流 ≥ 30秒/次

> **BUG警告**: msgSvrIds 是逗号分隔字符串，不是JSON数组！
> 错误: `{"msgSvrIds": ["id1", "id2"]}`
> 正确: `{"msgSvrIds": "id1,id2"}`

---

## 接口6: `/open/trans/wechatAmrTrans` — 语音转码

**状态**: 已测试
**结论**: AMR→MP3格式转换（非语音转文字），受IP白名单限制，不可用

---

## 销售微信号

| wxid | 姓名 |
|------|------|
| `wxid_am3kdib9tt3722` | 可欣(乐乐) |
| `wxid_p03xoj66oss112` | 小杰(jay) |
| `wxid_cbk7hkyyp11t12` | 霄剑(Chen) |
| `wxid_aufah51bw9ok22` | Fiona |
| `wxid_idjldooyihpj22` | 晴天喵 |
| `wxid_rxc39paqvic522` | Joy |

---

## 关键数据表

### chat_messages
- `msg_svr_id` (UNIQUE) — 消息去重键
- `wechat_id` — 客户/发言者wxid
- `sender_type` — 'sales' / 'customer'
- `content` — 文本内容
- `msg_type` — 消息类型
- `sent_at` — 发送时间(UTC)
- `file_url` — 文件URL
- `room_id` — 群ID（私聊为NULL）
- `sales_id` — 销售UUID
- `customer_id` — 客户UUID

### contacts
- `wechat_id` + `sales_wechat_id` (UNIQUE) — 联合唯一
- 13,826条记录（截至2026-03-08）
