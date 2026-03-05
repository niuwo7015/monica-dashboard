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

### 4. 获取聊天数据(短语音和文本) — 有问题
- Path: `/open/wechat/records`
- 参数需要friendWechatId，用F852466674(HONEY微信号)查询返回空
- **可能原因**: friendWechatId需要的是好友的微信ID(wxid)而非微信号(alias)
- 建议: 用allRecords接口替代

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
