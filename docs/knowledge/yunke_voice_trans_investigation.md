# 云客语音转码接口排查报告

> 排查日期: 2026-03-06
> 排查接口: `/open/trans/wechatAmrTrans`
> 核心问题: 这个接口能否替代阿里云百炼做语音转文字？

---

## 结论（TL;DR）

**暂时无法确认，需在阿里云服务器上实测。** 但根据接口命名和现有数据分析，**大概率是音频格式转换（AMR→MP3），不是语音转文字。**

| 维度 | 发现 |
|------|------|
| 接口是否存在 | **是**，返回IP白名单拦截（非404） |
| 公开文档 | **无**，云客不公开API文档，phone.yunkecn.com/open/doc 需认证 |
| 参数格式 | **未知**，需从服务器实测 |
| 功能推断 | "AmrTrans" = AMR Transcode（格式转换），非 Transcribe（转文字） |
| 能否替代百炼 | **大概率不能** — 见下方分析 |

---

## 排查过程

### 1. 本地API测试（被IP白名单拦截）

从本地（IP: 223.104.79.170）调用云客API，所有请求均返回：
```json
{"message":"ip223.104.79.170地址无效,非法调用开放资源","success":false}
```

云客API在网关层做IP校验，白名单IP为 `119.23.44.77`（阿里云服务器）。**所有路径都返回同样的IP拦截错误**，无法区分哪个接口真正存在。

已测试的参数组合（所有都被IP拦截，未到达业务逻辑层）：
- 参数名: url, fileUrl, file, voiceUrl, amrUrl, audioUrl, mediaUrl, filePath（共8种）
- 附加参数: wechatId, userId, msgSvrId 各种组合
- HTTP方法: POST JSON, POST form-urlencoded, GET
- Content-Type: application/json, application/x-www-form-urlencoded

### 2. 替代路径测试

测试了16个可能的路径变体，全部被IP拦截（无法区分404和真实接口）：
- /open/wechat/voiceTrans
- /open/wechat/voice/trans
- /open/trans/voice
- /open/trans/amrToMp3
- /open/trans/voiceToText
- /open/wechat/amrTrans
- /open/trans/wechatVoice
- /open/wechat/voiceToText
- /open/trans/audioToText
- /open/wechat/voice
- /open/trans/amr
- /open/trans/speechToText
- /open/wechat/speech
- /open/wechat/mediaToText
- /open/api/trans/wechatAmrTrans
- /open/wechat/mediaToText

### 3. 文档搜索

| 来源 | 结果 |
|------|------|
| 云客官网 yunkecn.com | 纯营销页面，无API文档入口 |
| phone.yunkecn.com/doc | 404 |
| phone.yunkecn.com/open/doc | 返回 `{"企业未认证"}`（说明文档系统存在但需认证） |
| open.yunkecn.com | SSL证书错误 |
| 搜索引擎 | "wechatAmrTrans" 全网零结果 |
| 云客客服电话 | 400-626-9560（未拨打） |

### 4. 关键推断：这是格式转换，不是语音转文字

**接口名称分析：**
- `wechat` = 微信相关
- `Amr` = AMR格式（微信语音原生格式）
- `Trans` = Transcode（转码），不是 Transcribe（转写）
- 路径 `/open/trans/` 也暗示 transcode

**现有数据佐证：**
- 云客OSS上的语音文件已经是 **MP3格式**（`yunke-pcfile.oss-cn-beijing.aliyuncs.com/wechat-voice/xxx.mp3`）
- 微信原生语音是AMR/SILK格式
- 云客很可能内部已经用了这个接口把AMR转成MP3再存到OSS
- 交接文档里称其为"语音转码接口"（不是"语音转文字接口"）

**如果是格式转换 → 不能替代百炼。** 百炼做的是语音识别（Speech-to-Text），把音频变成文字。格式转换只是把AMR变成MP3，仍然是音频。

---

## 现有语音转文字方案

| 维度 | 当前方案（阿里云百炼） |
|------|----------------------|
| 模型 | paraformer-v2 |
| SDK | dashscope |
| 输入 | MP3 URL（已在云客OSS上） |
| 输出 | 文字 |
| 已转译 | 13,977条 |
| 脚本 | scripts/03_voice_transcriber.py |
| 费用 | 收费（按量计费） |

---

## 下一步行动

### 必做：在阿里云服务器上实测

测试脚本已准备好：`scripts/test_yunke_voice_trans.py`

**操作步骤：**
1. 阿里云控制台 → 轻量应用服务器 → 远程连接 → Workbench一键连接
2. 通过Workbench左侧文件管理器，将脚本内容粘贴到 `/tmp/test_yunke_voice_trans.py`
3. 执行：`python3 /tmp/test_yunke_voice_trans.py`
4. 观察哪些参数组合返回了 `success: true`
5. 检查返回的 `data` 字段是文字还是音频URL

### 可选：联系云客技术支持

- 电话: 400-626-9560
- 问题: `/open/trans/wechatAmrTrans` 的参数格式、功能说明（是转码还是转文字）、是否额外收费
- phone.yunkecn.com/open/doc 有认证后的文档系统，可让云客开通

### 如果确认是格式转换（不是转文字）

那它对我们**没有价值** — 云客OSS上的语音文件已经是MP3，不需要再转码。继续用阿里云百炼做语音转文字。

### 如果确认能做语音转文字

需要进一步验证：
1. 转写质量是否不低于 paraformer-v2
2. 是否免费（包含在云客服务费中）还是单独计费
3. 是否支持批量/并发调用
4. 响应延迟是否可接受

---

## 附：认证信息

- COMPANY: `5fri8k`
- PARTNER_ID: `pDB33ABE148934DD081FD7D4C80654195`
- SIGN_KEY: `F446226EBF084CF6AAC00E`
- API域名: `https://phone.yunkecn.com`
- IP白名单: `119.23.44.77`
- 签名: `MD5(SIGN_KEY + COMPANY + PARTNER_ID + timestamp毫秒).toUpperCase()`
- API到期: 2026-03-20

## 测试用语音URL

```
https://yunke-pcfile.oss-cn-beijing.aliyuncs.com/wechat-voice/msg_071034020326478e4d2c279102.mp3
```
