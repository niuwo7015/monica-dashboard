# T-032 执行报告：订单表wechat_id脏数据修复

**执行时间**: 2026-03-15
**执行人**: Claude Code

---

## 背景

orders表wechat_id字段有222条（12.3%）未被feishu_sync_wiki_orders.py反查成功，保留了飞书原始数据。三种格式混存：
- 云客内部ID（wxid_开头） — 87.7%已反查成功
- 微信号/昵称 — 销售在飞书手填的，反查失败保留原样
- 群聊名称 — 如"莫妮卡高定家具052301-沙发"

## 修复结果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 匹配成功（matched） | 1587（87.7%） | 1715（94.8%） |
| 未匹配（unmatched） | 222（12.3%） | 76（4.2%） |
| 空值（NULL） | 0 | 18 |

共修复146条：128条匹配成功 + 18条垃圾置NULL。

## 修复方法

### 1. nickname（昵称）精确匹配 — 103条订单（36种dirty_wid）
通过contacts表的nickname字段反查，排除多义匹配（Zoe/Lydia/Cecilia各有2-3个同名联系人）。
- 群聊名称（如"莫妮卡高定家具052301-沙发"）→ 对应chatroom的wechat_id
- 个人昵称（如"爱甜甜"、"诺言诺语"、"Sophia Qin"）→ 对应个人wechat_id

### 2. 特殊格式wxid提取 — 6条
"-腓腓喝O泡-/wxid_l0ixp2gtopnb22" → 提取"wxid_l0ixp2gtopnb22"

### 3. 模糊匹配群聊前缀 — 13条
去掉"群聊："/"群聊"前缀后匹配contacts.nickname：
- "群聊050507模块沙发" → "莫妮卡050507模块沙发"对应的chatroom
- "群聊：莫妮卡高定家具051702-模块沙发" → 对应chatroom
- "莫妮卡高定家具072913-"（不完整）→ "莫妮卡高定家具072913-像素沙发"对应的chatroom
- "群聊：莫妮卡050405像素沙发" → 对应chatroom

### 4. 垃圾数据置NULL — 18条
- "无"（2条）、"2025/09/5"（2条）、"11月15日"（2条）— 非微信号
- "🍍👶🐑"（2条）— 纯emoji昵称无匹配
- "群聊050414"（6条）— 无对应contacts记录
- "群聊050507模块沙发"（1条残余）— 编码问题

## 剩余76条（无法自动修复）

高频：Matt(8)、tldbkppszd-99(6)、kk616900(6)、LawyerEmma2023(5)、Vivixiaokeaimua(4)、Proof(4)、XOXOY2K(4)、zkkkkk-98(4)

这些微信号/昵称在contacts表中完全无记录，可能是：
- 已删除的联系人
- 未通过云客管理的联系人
- 销售手填错误

## 脚本增强

修改 `scripts/feishu_sync_wiki_orders.py` 的 `resolve_wechat_id` 函数，新增3层兜底：
1. **垃圾值过滤** — "无"、日期格式（"X月X日"/"YYYY/M/D"）直接返回NULL
2. **wxid提取** — 从"昵称/wxid_xxx"格式中用正则提取
3. **nickname（昵称）唯一匹配** — alias/remark匹配失败后，用contacts.nickname做兜底反查

`build_wechat_lookup` 函数新增返回 `nickname_exact`（昵称唯一匹配表），传入反查流程。

## 注意事项

- Supabase Management API对中文字符串的精确匹配（`=`）有编码兼容问题，LIKE可正常工作
- 群聊名称匹配到的是chatroom类型的contacts，不是个人客户——但至少建立了关联，优于完全无匹配
- 多义昵称（Zoe/Lydia/Cecilia）未处理，需人工确认对应哪个联系人

## 遗留问题

- 剩余76条需人工确认或等联系人被云客同步后自动关联
- feishu_sync_wiki_orders.py已增强，新订单同步会自动用新逻辑，但需部署到服务器
