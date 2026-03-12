# 云客API完整参考文档

> 文档生成时间: 2026-03-09
> 来源: https://crm.yunkecn.com/cms/settings/openPreView (基础版 + 高级版)

---

## 一、9个核心问题的回答

### Q1: 是否有webhook/事件回调机制？

**有，但有限制。**

- **基础版**只有一个回调：**添加微信好友结果状态回调**，仅推送好友添加的结果（待验证/成功/失败），**不推送新聊天消息**。需在PC管理后台→接口申请配置页面→回调配置中配置。
- **高级版（渠道专用）** 2025-10-16新增了：获取所有回调类型接口 + 设置回调地址接口。标注为"渠道专用"，需确认账号权限。
- **微联络模块**（高级版）有多个回调接口：新增好友事件上报、加好友任务结果上报、群发任务结果上报、离线通知等。
- **结论：基础版没有聊天消息的webhook。如需实时推送，需升级到高级版或使用微联络模块。当前方案只能用轮询。**

### Q2: allRecords接口的真实限流是多少？

**5秒调用一次。**

- 接口：`/open/wechat/allRecords`
- 限频：**5秒内最多调用一次**（文档原文）
- **重大更新（2026-01-12）：取消了每次最多返回2000条的限制！** 现在不限返回条数。
- 按公司码拉取全部，根据timestamp增量拉取**1小时内**的全部微信数据
- timestamp参数：**13位毫秒时间戳**
- timestamp需小于当前时间30分钟以上（数据存储有延迟）
- 用返回的`end`值作为下次查询的开始时间
- 支持所有消息类型（文本、图片、短语音、视频、文件、链接、定位、GIF、引用、拍一拍、名片、系统消息等）

### Q3: records接口的真实限流是多少？

**分两种场景，限流不同：**

- 接口：`/open/wechat/records`
- **场景1（时间戳翻页）**：timestamp + direction参数 → **5秒调用一次**
- **场景2（时间区间查询）**：start + end参数 → **2秒调用一次**，时间间隔不超过3天
- 需要传 friendWechatId + wechatId + userId（按好友逐个查询）
- **只返回文本和短语音消息**（不像allRecords返回所有类型）
- start/end格式：**日期字符串**，如 `"2020-04-22 13:39:29"`
- S-004测试2秒可行是正确的（场景2的限频就是2秒）
### Q4: 是否有批量导出/全量拉取接口？

**有！allRecords就是。**

- allRecords (`/open/wechat/allRecords`) 按公司码拉取**全部员工的全部聊天数据**，不需要按好友逐个拉
- 每次返回1小时窗口的数据，**不再有2000条上限**（2026-01-12更新）
- 这才是正确的拉取方式，不需要先获取好友列表再逐个拉records
- 高级版还有**冷库接口** `open/wechat/wechatHistoryChatRecord`，用于查2024-02-01之前的历史数据

### Q5: getAllFriendsIncrement vs friends接口的区别？

**getAllFriendsIncrement是增量查询接口，是目前推荐的好友列表接口。**

- 接口：`/open/wechat/getAllFriendsIncrement`
- 限频：**5秒调用一次**
- 解决了老版getAllFriendsV2的慢查询问题
- 支持两种查询模式：`queryMode=createTime`（按创建时间）或 `queryMode=updateTime`（按更新时间）
- 返回最多2000条/次（相同时间数据可能超2000）
- **有lastChatTime字段**（13位时间戳），可用来筛选有聊天记录的好友
- 时间格式：`yyyy-MM-dd HH:mm:ss`（日期字符串）
- 增量机制：用返回的`queryEndTime` + 1秒作为下次的`startTime`

**优化建议：用getAllFriendsIncrement的lastChatTime字段预筛选有聊天的好友，跳过从未聊天的。**

### Q6: start/end参数的真实格式？

**取决于接口，两种格式都存在：**

| 接口 | 参数名 | 格式 | 示例 |
|------|--------|------|------|
| allRecords | timestamp | **13位毫秒时间戳** | `1664899200000` |
| records（场景1） | timestamp | **13位毫秒时间戳** | `1524799715000` |
| records（场景2） | start/end | **日期字符串** | `"2020-04-22 13:39:29"` |
| getAllFriendsIncrement | startTime | **日期字符串** | `"2022-01-05 00:00:00"` |
| 冷库 wechatHistoryChatRecord | start | **13位毫秒时间戳** | `1743131046000` |

**结论：技术文档说"秒级时间戳"是错误的。allRecords用13位毫秒时间戳，records的时间区间模式用日期字符串。**

### Q7: 是否有增量拉取机制？

**有，所有主要接口都支持增量。**

- **allRecords**：用返回的`end`值作为下次的`timestamp`，实现游标式增量拉取。还有`createTimestamp`参数处理同一时间超2000条的情况。
- **records（场景1）**：timestamp + direction(up/down) 翻页机制
- **getAllFriendsIncrement**：用返回的`queryEndTime` + 1秒作为下次`startTime`
- **冷库接口**：同allRecords机制，用返回的`end`作为下次的`start`

### Q8: API调用配额/日限额？

**文档中没有提到每日总调用次数限制。** 只有单次调用的频率限制（5秒/次或2秒/次）。没有发现日配额、月配额或总量限制的说明。

### Q9: 高级版 vs 基础版有什么区别？

| 特性 | 基础版 | 高级版 |
|------|--------|--------|
| 聊天数据 | allRecords（实时）+ records（按好友） | 冷库历史聊天记录（2024-02前） |
| 好友列表 | getAllFriendsIncrement | 无独立接口 |
| 回调/Webhook | 仅好友添加回调 | 获取所有回调类型 + 设置回调地址（渠道专用） |
| 额外模块 | 无 | 抖音、小红书、AI外呼、whatsApp、定位同步、推送消息给手机端 |
| 沟通统计 | 无 | 微信沟通人数统计、好友沟通统计详情 |

---

## 二、鉴权机制

- **Header参数**：company, partnerId, timestamp, key, sign, Content-Type
- **签名算法**：`sign = MD5(key + company + partnerId + timestamp).toUpperCase()`
- **timestamp**：Unix毫秒时间戳（13位），服务端校验±5分钟内有效

---

## 三、优化建议

### 当前方案的问题
用records接口按好友逐个拉取，13000好友×10秒/次 = 36小时，而且records只返回文本+语音。

### 推荐方案：改用allRecords

1. **用allRecords替代records**：按公司维度拉取，1小时一个窗口，5秒/次，不限条数。不需要好友列表。
2. **速度估算**：假设有1年数据 = 8760小时窗口 × 5秒 = 12.2小时。很多小时可能没数据（快速跳过），实际更快。
3. **allRecords返回所有消息类型**，数据更完整。
4. **增量维护**：首次全量拉取后，定时用allRecords增量拉取新数据。

### 关于实时推送
- 基础版无聊天消息webhook，只能轮询
- 用allRecords每5秒轮询一次，延迟约30分钟（timestamp需小于当前时间30分钟）

---

## 四、重要勘误

### [2026-03-09] allRecords 群聊数据结论修正

- **旧结论（已作废）**：~~allRecords不返回群内客户文本，群聊需用records接口补充~~
- **新结论（T-001群聊验证确认）**：allRecords 已确认包含群聊客户消息（`mine=false` 的群聊记录即为客户发言），无需再用 records 接口补充群聊数据
- **验证方式**：T-001全量同步过程中，从allRecords返回数据中筛选群聊（roomWechatId非空）+ mine=false，确认包含客户文本消息
- **影响**：CLAUDE.md 中"allRecords不返回群聊客户文本"规则同步废弃；全量/增量同步方案不再需要 records 接口作为群聊补充

---

## 五、更新日志摘要（与本项目相关的）

| 日期 | 内容 |
|------|------|
| 2026-01-12 | **allRecords取消2000条上限** |
| 2025-10-16 | 高级版新增回调类型查询和设置回调地址接口 |
| 2025-08-12 | getAllFriendsIncrement增加description和noteDes字段 |
| 2025-06-25 | 获取微信好友/微信群接口增加10分钟请求频率限制 |
| 2025-04-29 | 新增微信查询历史聊天记录（冷库）接口 |
| 2025-11-27 | allRecords新增个人名片、系统消息类型返回 |