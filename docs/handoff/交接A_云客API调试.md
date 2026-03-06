# 交接文件A：云客API调试窗口

> 目的：在阿里云服务器上完成云客API对接调试，确认所有接口可用，找到HONEY的talker ID

---

## 一、认证信息

- 企业串码(COMPANY): `5fri8k`
- 管理员ID(PARTNER_ID): `pDB33ABE148934DD081FD7D4C80654195`
- 签名KEY: `F446226EBF084CF6AAC00E`
- API域名: `https://phone.yunkecn.com`
- 签名算法: `MD5(签名KEY + COMPANY + partnerId + timestamp).toUpperCase()`
- IP白名单: `119.23.44.77`（阿里云轻量服务器）

## 二、服务器信息

- 阿里云轻量应用服务器，华南1（深圳）
- 名称: Ubuntu-zxvx
- 公网IP: 119.23.44.77
- 实例ID: ee4f6768860e42a89f32cc2561bccfd0
- 连接方式: 阿里云控制台 → 轻量应用服务器 → 远程连接 → Workbench一键连接
- 用户: admin
- Python3已安装，requests已安装
- 脚本存放: /tmp/ 目录，通过Workbench左侧文件管理器新建文件

## 三、已验证通过的接口

### 1. 获取微信账号 ✅
- Path: `/open/wechat/accounts`
- 返回6个微信号:
  - `wxid_am3kdib9tt3722` = 莫妮卡摩卡高定家具-乐乐（可欣的号）
  - `wxid_p03xoj66oss112` = 莫妮卡摩卡高定家具-jay（小杰）
  - `wxid_cbk7hkyyp11t12` = 莫妮卡摩卡高定家具-Chen（霄剑）
  - `wxid_aufah51bw9ok22` = 莫妮卡摩卡高定家具-Fiona
  - `wxid_idjldooyihpj22` = 晴天喵
  - `wxid_rxc39paqvic522` = jiapai橙遇Joy

### 2. 获取好友列表 ✅
- Path: `/open/wechat/friends`
- 参数: `{"wechatId":"wxid_am3kdib9tt3722","userId":AID,"timestamp":"0"}`
- 返回分页数据，pageSize=20，totalCount=4048
- 每个好友有: id(微信id), alias(微信号), name, remark, delete(0/1), addTime, region等

### 3. 增量获取全部聊天记录 ✅
- Path: `/open/wechat/allRecords`
- 参数: `{"timestamp":毫秒时间戳,"createTimestamp":0}`
- **按公司维度拉取**，不需要指定好友ID
- 每次返回1小时内的数据，用返回的end值翻页
- 5秒调用一次
- 返回所有消息类型: 1文本,2图片,3语音,4视频,8GIF,9文件,10链接等
- 消息字段: mine, talker, wechatId, type, text, file, timestamp, msgSvrId

### 4. 获取指定好友/群的聊天记录 ✅（2026-03-06修复）
- Path: `/open/wechat/records`
- **之前调不通的原因**: 缺少必填参数 `userId`
- **解决**: `userId` 传 `partnerId`（即 `pDB33ABE148934DD081FD7D4C80654195`）
- 参数:
  ```json
  {
    "friendWechatId": "好友wxid或群ID@chatroom",
    "wechatId": "销售微信号",
    "userId": "pDB33ABE148934DD081FD7D4C80654195"
  }
  ```
- 返回结构: `data.messages` 数组，`data.hasNext`/`data.hasLast` 翻页标记
- **群聊消息中 `talker` = 发言者wxid**（与allRecords不同！）
- 详见下方「六、群聊发言者身份」章节

## 四、待完成的调试任务

### 任务1: 找到HONEY的talker ID（最高优先）
- HONEY微信号: F852466674，备注: Z26.3.1岩石
- 是可欣(wxid_am3kdib9tt3722)的客户
- 3月1号11:00-16:00有234条消息
- 需要用allRecords从3月1号10点开始扫，找talker中包含HONEY相关的ID
- 脚本（创建为/tmp/test_all6.py）:

```python
import hashlib,time as t,json,requests
COMPANY="5fri8k"
KEY="F446226EBF084CF6AAC00E"
AID="pDB33ABE148934DD081FD7D4C80654195"
BASE="https://phone.yunkecn.com"
def call(p,d):
    ts=str(int(t.time()*1000))
    sign=hashlib.md5((KEY+COMPANY+AID+ts).encode()).hexdigest().upper()
    h={"Content-Type":"application/json","partnerId":AID,"company":COMPANY,"timestamp":ts,"sign":sign}
    return requests.post(BASE+p,json=d,headers=h).json()

# March 1 2026 10:00 UTC+8
end_ts = 1772186400000
for i in range(50):
    r=call("/open/wechat/allRecords",{"timestamp":end_ts,"createTimestamp":0})
    if not r.get("data"):
        break
    d=r["data"]
    msgs=d.get("messages",[])
    end_ts=d.get("end",0)
    kexin_msgs=[m for m in msgs if m.get("wechatId")=="wxid_am3kdib9tt3722"]
    if kexin_msgs:
        print(f"round {i}: {len(kexin_msgs)} kexin msgs")
        for m in kexin_msgs:
            talker=m.get("talker","")
            txt=(m.get("text","") or "")[:50]
            mine="S" if m.get("mine") else "C"
            print(f"  [{mine}] talker={talker} text={txt}")
    else:
        print(f"round {i}: 0 kexin")
    if len(msgs)==0:
        break
    t.sleep(5)
print("DONE")
```

### 任务2: 确认records接口用法
- 找到HONEY的talker ID后，用它调 `/open/wechat/records` 确认能否按好友维度拉聊天记录
- 这个接口支持时间范围查询(start/end)，比allRecords更精准

### 任务3: 测试其他接口
- 微信删除好友详情: 找到正确的接口路径
- 获取微信新增好友统计: 确认接口路径和返回格式
- 语音转码接口: `/open/trans/wechatAmrTrans`

## 五、注意事项

- allRecords接口每次返回1小时数据，5秒调一次
- 时间戳是13位毫秒数
- records接口的时间区间最多3天
- API服务到期时间: 2026-03-20，需续期
- 服务器很小(2vCPU/1GiB)，别跑太重的任务

## 六、群聊发言者身份（2026-03-06 调查结论）

### 问题
群聊消息（talker含@chatroom）通过 allRecords 拉到的数据里没有群内发言者的微信ID。但云客后台手动导出的xlsx有"发送人"字段。

### 结论：用 records 接口解决 ✅

#### allRecords 的限制（不可用于群聊完整记录）
- **不返回群内非销售成员的文本消息**（type=1, mine=false = 0条）
- 只返回：销售自己发的消息（mine=true）+ 系统通知（type=15，撤回/入群等）
- `talker` 字段 = 群ID，不是发言者

#### records 接口（正确方案）
- 正常返回群内所有成员的消息，包括客户文本
- **`talker` 字段 = 发言者wxid**
- `oriTalker` / `roomid` = 群ID

#### 调用示例
```
POST https://phone.yunkecn.com/open/wechat/records

请求头: 标准签名头（partnerId, company, timestamp, sign）

请求体:
{
  "friendWechatId": "57014312248@chatroom",
  "wechatId": "wxid_am3kdib9tt3722",
  "userId": "pDB33ABE148934DD081FD7D4C80654195"
}
```

#### 两个接口对比

| | allRecords | records |
|---|---|---|
| 客户文本消息(type=1,mine=false) | ❌ 不返回 | ✅ 返回 |
| talker 字段含义 | 群ID | **发言者wxid** |
| 群ID在哪个字段 | talker | oriTalker / roomid |
| userId 参数 | 不需要 | **必填，传partnerId** |
| 适用场景 | 批量拉私聊 | 拉指定群/好友的完整记录 |

#### records 返回的群聊消息结构
```json
{
  "mine": false,
  "talker": "wxid_lfag5f4qitgp12",      // ★ 发言者wxid
  "wechatId": "wxid_am3kdib9tt3722",     // 所属销售微信号
  "oriTalker": "57014312248@chatroom",   // 群ID
  "roomid": "57014312248@chatroom",      // 群ID
  "text": "那我要在哪備注 下單的產品呀",
  "type": 1,
  "msgSvrId": "1100782783502033865",
  "isDel": "0",
  "hasHead": true,
  "timestamp": 1772711221000
}
```

#### 实测验证
群 `57014312248@chatroom`，records 返回30条，其中19条 mine=false type=1（客户文本），talker 均为 `wxid_lfag5f4qitgp12`。同群用 allRecords 拉取客户文本 = 0条。

#### 补充发现
- allRecords 中 type=21（引用回复）的 `referMsgJson` 字段包含被引用消息的发言者wxid和昵称，可作为辅助数据源
- friends 接口传 `type=2` 可过滤群列表，含 `ownerWchatId`（群主），但无群成员列表
- accounts 返回的 `account` 字段不是 userId（传入会报"用户不存在"）
- 所有群成员相关路径（groupMembers、chatroom/members等30+路径）均404，云客不提供群成员接口

#### 后续行动
将 `yunke_sync.py` 群聊消息拉取逻辑从 allRecords 改为 records 接口：
1. 通过 friends 接口（type=2）获取所有群列表
2. 逐群调用 records 接口拉取完整群聊记录
3. 从 talker 字段获取发言者wxid
