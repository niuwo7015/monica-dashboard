# 云客好友来源类型（fromType）对照表

> 云客API `/open/wechat/friends` 返回的好友对象中，`fromType` 字段表示该好友的添加来源渠道。
> 该字段直接透传自微信个人号内部的好友来源类型（AddScene/verifyType），非企业微信的 `add_way`。

## 已确认的 fromType 值

| fromType值 | 来源渠道 | 英文 | 确认方式 |
|-----------|---------|------|---------|
| 0 | 未知来源 / 群成员（非好友） | Unknown / Group member | 行业惯例 + 企微平行对照 |
| 1 | QQ号搜索 | Search QQ number | wechatsdk.com 文档 |
| 3 | 微信号搜索 | Search WeChat ID | wechatsdk.com 文档 |
| 6 | 好友验证消息（默认值） | Friend verification (default) | wechatsdk.com 文档 |
| 14 | 群聊添加 | From group chat | wechatsdk.com 文档 |
| 15 | 手机号搜索 | Search phone number | wechatsdk.com 文档 |
| 18 | 附近的人 | People nearby | wechatsdk.com 文档 |
| 24 | 摇一摇 | Shake Shake | wechatsdk.com 文档 |

## 待确认的 fromType 值

| fromType值 | 推测来源渠道 | 确认方式 |
|-----------|------------|---------|
| 17 | 名片分享推荐 | 未确认，推断 |
| 25 | 漂流瓶 | 未确认，推断（功能已下线） |
| 30 | 扫一扫二维码 | 未确认，推断 |
| 81 | 朋友圈广告 / 微信广告 | 未确认，推断 |

## 实际API数据中观察到的值

从我方6个销售微信号的云客好友列表API实际返回中，观察到以下 fromType 值：

| fromType值 | 出现场景 | 推断含义 |
|-----------|---------|---------|
| "0" | 群聊记录中出现 | 未知来源或群成员（从群里拉取时无好友来源） |
| "3" | 个人好友 | 通过微信号搜索添加 |
| "6" | 个人好友 | 好友验证消息（默认，具体来源不明确时使用此值） |
| "14" | 个人好友 | 通过群聊添加的好友 |
| "15" | 个人好友 | 通过手机号搜索添加 |
| "81" | 个人好友 | 可能是朋友圈广告/微信广告渠道（待验证） |

## 重要说明

### 关于 fromType=6

值 `6` 在 wechatsdk.com 文档中被定义为"好友验证消息（默认值）"，而非"扫描二维码"。当微信无法明确识别具体添加方式时（如对方已有你的微信号、历史迁移联系人等），会使用此默认值。因此 `fromType=6` 的好友可能来自多种渠道。

### 关于 fromType=0

值 `0` 通常表示"未知来源"。在群聊上下文中出现时，表示该记录是群成员而非通过好友关系添加的联系人。

### 关于 fromType=81

值 `81` 在所有公开文档中均未找到定义。根据微信功能特性和数值范围推测，可能对应"朋友圈广告"或"微信广告"渠道（高编号通常对应较新的功能）。需要通过以下方式验证：
1. 对比 fromType=81 的好友在微信客户端中显示的"来源"标签
2. 联系云客技术支持获取官方字段文档

### 企业微信 add_way 对照（注意：编号体系不同）

企业微信的 `add_way` 是另一套编号体系，不可与个人微信 `fromType` 混用：

| add_way | 含义 |
|---------|------|
| 0 | 未知来源 |
| 1 | 扫描二维码 |
| 2 | 搜索手机号 |
| 3 | 名片分享 |
| 4 | 群聊 |
| 5 | 手机通讯录 |
| 6 | 微信联系人 |
| 7 | 来自微信的添加好友申请 |
| 8 | 安装第三方应用时自动添加的客服人员 |
| 9 | 搜索邮箱 |
| 201 | 内部成员共享 |
| 202 | 管理员/负责人分配 |

## 数据来源

- 个人微信 fromType 值：[wechatsdk.com Add-Friend API](https://www.wechatsdk.com/en/docs/Contacts/Add-Friend.md)
- 企业微信 add_way 值：[企业微信开发者中心 - 获取客户详情](https://developer.work.weixin.qq.com/document/path/92114)
- 实际观察数据：云客API `/open/wechat/friends` 接口返回

## 后续验证计划

- [ ] 登录云客后台或联系云客技术支持，获取官方 fromType 字段文档
- [ ] 在微信客户端中抽样检查 fromType=6 和 fromType=81 的好友，核对"更多信息 > 来源"显示
- [ ] 查询Supabase contacts表 `SELECT from_type, COUNT(*) FROM contacts GROUP BY from_type` 统计分布
