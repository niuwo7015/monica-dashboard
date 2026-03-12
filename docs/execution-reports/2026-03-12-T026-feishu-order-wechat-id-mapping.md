# T-026: 飞书订单同步 wechat_id 映射问题排查与修复报告

**日期**: 2026-03-12
**状态**: 已修复

---

## 1. 问题描述

orders表960条记录，已知成交客户在orders表查不到（按wxid查）：
- 罗璇 (`wxid_vbogrguw9xtn22`)
- 黄逸婷 (`wxid_cf0hlovo4z1p21`)
- D-25.0717 (`wxid_8kvjlyd9so9a12`)

## 2. 根因（已确认）

**实际同步脚本是 `feishu_sync_wiki_orders.py`（T-016），不是 `feishu_sync_orders.py`（S-006）。**

S-006从未部署到服务器，服务器上只有 `feishu_sync_wiki_orders.py`。

飞书表格D列（微信号列）填的是**微信别名(alias)**，如 `TORSADE_L`、`wshytsw`、`DD_chiyue`，而非 `wxid_` 格式。脚本直接将alias原样写入orders.wechat_id，导致与contacts表（用wxid_格式的wechat_id）无法关联。

**3个"缺失"客户实际都在orders表里**，只是wechat_id存的是alias：

| 客户 | orders.wechat_id (旧) | contacts.wechat_id (wxid) |
|------|----------------------|--------------------------|
| 罗璇 | TORSADE_L | wxid_vbogrguw9xtn22 |
| 黄逸婷 | wshytsw | wxid_cf0hlovo4z1p21 |
| D-25.0717 | DD_chiyue | wxid_8kvjlyd9so9a12 |

## 3. 修复操作

### 3.1 feishu_sync_wiki_orders.py 增加反查逻辑

新增函数：
- `build_wechat_lookup()`: 从contacts表加载alias/remark → wechat_id映射（13,881条contacts → 14,460个唯一映射 + 564个歧义项）
- `resolve_wechat_id()`: 按优先级解析飞书D列值
  1. 已是wxid_格式 → 直接使用
  2. 精确匹配contacts.wechat_alias → 使用对应wxid
  3. 模糊匹配（substring in remark） → 唯一匹配则使用
  4. 多个匹配 → 打印warning跳过
  5. 无匹配 → 打印warning，保留原始值

dry-run验证（wiki 2026表，99条）：
- 4条已是wxid格式
- 83条精确匹配成功
- 1条模糊匹配成功
- 11条失败（7条"莫妮卡高定家具"展厅内部订单，3条"justin"歧义，1条无匹配）

### 3.2 修复已有960条orders数据

直接更新已有orders记录的wechat_id（alias → contacts.wechat_id）：
- **587条更新成功**，0条失败
- 修复后：604个唯一wechat_id中526个匹配contacts（87%）
- 剩余78个未匹配主要是"莫妮卡高定家具xxx"展厅内部订单（非客户好友）

### 3.3 验证3个目标客户

修复后直接按wxid查询全部命中：
- 罗璇 `wxid_vbogrguw9xtn22` → 2025-10-30, 12000元, 像素沙发
- 黄逸婷 `wxid_cf0hlovo4z1p21` → 2025-12-12, 18500元, 像素沙发
- D-25.0717 `wxid_8kvjlyd9so9a12` → 2025-07-17, 17717元, 花瓣沙发

### 3.4 全量好友同步补add_time

`yunke_pull_friends.py` 代码中 add_time 映射已存在（第178行）。
已在服务器后台启动全量同步（`/var/log/monica/pull_friends_backfill.log`），正在运行中。

## 4. 代码变更

- `scripts/feishu_sync_wiki_orders.py`: 新增 `build_wechat_lookup()` + `resolve_wechat_id()`，从repo新文件（之前只在服务器上）
- 已push到 GitHub `claude/elastic-easley` 分支
- 已部署到服务器 `/home/admin/monica-scripts/`

## 5. 仍存在的问题

| 问题 | 影响 | 建议 |
|------|------|------|
| 78个orders.wechat_id无法匹配contacts | 展厅内部订单，非真实客户好友 | 可标记为内部订单排除 |
| cron里 `feishu_sync_orders.py` 仍在跑但文件不存在 | 每30分钟报错一次 | 删除该cron行 |
| `feishu_sync_orders.py`（S-006）在repo中但从未使用 | 代码混淆 | 可删除或标记废弃 |
