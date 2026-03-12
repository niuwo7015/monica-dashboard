# T-026: 飞书订单同步 wechat_id 映射问题排查报告

**日期**: 2026-03-12
**状态**: 排查完成，含修复建议

---

## 1. 问题描述

orders表960条记录，但已知成交客户在orders表完全没有记录：
- 罗璇 (`wxid_vbogrguw9xtn22`)
- 黄逸婷 (`wxid_cf0hlovo4z1p21`)
- D-25.0717 (`wxid_8kvjlyd9so9a12`)

这些客户在飞书订单表里确实存在。

## 2. 同步脚本分析

### 2.1 唯一的同步脚本

只找到一个同步脚本：`scripts/feishu_sync_orders.py`（S-006），不存在 `feishu_sync_wiki_orders.py`。

### 2.2 飞书表格列结构（脚本中的COLUMN_MAP）

| 列号 | 飞书列 | 字段名 | 说明 |
|------|--------|--------|------|
| A (0) | 客户微信号 | customer_wechat_id | **直接填wxid** |
| B (1) | 客户姓名 | customer_name | 仅日志用，不入库 |
| C (2) | 下单日期 | order_date | 必填 |
| D (3) | 订单金额 | amount | |
| E (4) | 产品线 | product_line | |
| F (5) | 负责销售 | sales_name | |
| G (6) | 备注 | remark | |

### 2.3 wechat_id 映射逻辑 —— 根因所在

**脚本的映射逻辑极其简单：飞书表格A列直接就是 `customer_wechat_id`，原样写入orders表。**

```python
# feishu_sync_orders.py 第219行
wechat_id = str(raw.get('customer_wechat_id', '') or '').strip()
if not wechat_id:
    skipped += 1
    continue
```

关键发现：
- **没有join contacts表**
- **没有通过备注名/手机号/昵称反查wechat_id**
- **飞书表格A列必须直接填写wxid_xxx格式的微信号**
- 如果A列是空的、或填的是备注名/手机号而非wxid，该行直接跳过

### 2.4 销售映射

销售用的是硬编码的名称→wxid映射表 `SALES_NAME_TO_WECHAT`（第55-67行），将飞书F列的销售名称转为 `sales_wechat_id`。

## 3. 根因分析

### 3.1 三个客户缺失的可能原因

**最可能的原因：飞书订单表A列（客户微信号列）没有填写这3个客户的wxid**

具体可能的情况：
1. **A列填的是备注名而非wxid** — 如填了"罗璇"而非"wxid_vbogrguw9xtn22"，脚本会把"罗璇"当成wechat_id写入（不会匹配到任何contacts记录），或者如果A列为空则直接跳过
2. **A列为空** — 脚本第220行会跳过该行
3. **日期格式无法解析** — 脚本第227行会跳过无效日期行
4. **该行在飞书表格中的行号发生了变化** — feishu_row_id用的是 `row_{行号}`，如果飞书表格中间插入/删除了行，可能导致数据错位

### 3.2 成功匹配的960条是怎么来的

orders表中960条wechat_id不为空的记录，**全部来自飞书表格A列的原始值**。也就是说：
- 飞书表格里谁填了正确的wxid格式，就能成功同步
- 飞书表格里如果A列就是写的wxid_xxx，那就直接入库

**没有任何反查/join/模糊匹配逻辑。**

## 4. 设计缺陷总结

| 缺陷 | 说明 | 影响 |
|------|------|------|
| **飞书依赖人工填wxid** | 飞书表格A列要求填写wxid_xxx格式的微信号，这对于人工填写极不友好 | 漏填、填错导致客户丢失 |
| **无反查逻辑** | 不通过备注名、手机号、昵称等字段关联contacts表反查wxid | 无法自动匹配客户 |
| **行号去重脆弱** | feishu_row_id = `row_{行号}`，飞书表格增删行后行号变化 | 数据错位/重复 |
| **无匹配失败告警** | 跳过的行只有日志，无汇总告警 | 运营不知道丢了多少客户 |

## 5. 修复建议

### 方案A：增加反查逻辑（推荐）

在 `parse_rows()` 中增加一步：如果A列不是wxid格式（不以 `wxid_` 开头），则尝试通过以下字段反查 contacts 表：
1. `contacts.remark` = A列值（备注名匹配）
2. `contacts.phone` = A列值（手机号匹配）
3. `contacts.nickname` = A列值（昵称匹配）

如果反查到唯一结果，用该 contacts.wechat_id 替代A列值。

### 方案B：改飞书表格设计

在飞书表格中增加一个隐藏列，由脚本自动回填wxid（但CLAUDE.md规定飞书写权限已关闭，此方案不可行）。

### 方案C：导出飞书原始数据排查

先用 `--dry-run` 跑一次同步脚本，看飞书表格A列实际填的是什么。这可以精确定位3个缺失客户的行数据。

**建议先执行方案C确认根因，再实施方案A。**

## 6. yunke_pull_friends.py 中 add_time 字段排查

### 6.1 结论：add_time 已有映射逻辑

`yunke_pull_friends.py` 第178行已经包含 add_time 的映射：

```python
'add_time': timestamp_to_iso(friend.get('addTime')),
```

映射链路：
- 云客API返回字段：`addTime`（毫秒时间戳）
- 通过 `timestamp_to_iso()` 转为ISO格式
- 写入 contacts 表的 `add_time` 字段

### 6.2 如果add_time为空的可能原因

1. **云客API没返回addTime字段** — 部分老好友可能不带这个字段
2. **addTime值为0或null** — `timestamp_to_iso()` 会返回None，None在第186行被过滤掉
3. **之前跑的旧版本脚本没有这个映射** — M-019修复前的代码可能不同

### 6.3 建议

代码中 add_time 映射已存在且正确。如果当前 contacts 表中大量 add_time 为空，只需重新执行一次全量好友同步即可补上（前提是云客API确实返回了addTime）：

```bash
ssh admin@119.23.44.77 "cd /home/admin/monica-scripts && python3 yunke_pull_friends.py"
```

---

**下一步行动**（需Woniu确认）：
1. 在服务器上 `--dry-run` 跑一次飞书同步，查看飞书表格A列原始数据
2. 确认是否需要实施方案A（反查逻辑）
3. 确认是否执行全量好友同步补充add_time
