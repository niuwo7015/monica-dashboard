#!/usr/bin/env python3
"""
云客语音转码接口排查脚本
在阿里云服务器上运行（IP白名单: 119.23.44.77）
用法: python3 /tmp/test_yunke_voice_trans.py
"""
import hashlib, time, json, sys

try:
    import requests
except ImportError:
    print("安装 requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

COMPANY = "5fri8k"
KEY = "F446226EBF084CF6AAC00E"
AID = "pDB33ABE148934DD081FD7D4C80654195"
BASE = "https://phone.yunkecn.com"

# 已知的语音文件URL（mp3格式，从云客OSS）
VOICE_URL_MP3 = "https://yunke-pcfile.oss-cn-beijing.aliyuncs.com/wechat-voice/msg_071034020326478e4d2c279102.mp3"

def make_headers(content_type="application/json"):
    ts = str(int(time.time() * 1000))
    sign = hashlib.md5((KEY + COMPANY + AID + ts).encode()).hexdigest().upper()
    return {
        "Content-Type": content_type,
        "partnerId": AID,
        "company": COMPANY,
        "timestamp": ts,
        "sign": sign
    }

def call_post(path, data, content_type="application/json"):
    h = make_headers(content_type)
    try:
        if content_type == "application/json":
            r = requests.post(BASE + path, json=data, headers=h, timeout=30)
        else:
            r = requests.post(BASE + path, data=data, headers=h, timeout=30)
        return r.status_code, r.text[:1000], r.headers.get("Content-Type", "")
    except Exception as e:
        return -1, str(e)[:500], ""

def call_get(path, params=None):
    h = make_headers()
    try:
        r = requests.get(BASE + path, params=params, headers=h, timeout=30)
        return r.status_code, r.text[:1000], r.headers.get("Content-Type", "")
    except Exception as e:
        return -1, str(e)[:500], ""

def section(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def test(label, code, body, ctype=""):
    status = "OK" if code == 200 else f"HTTP {code}"
    print(f"  [{status}] {label}")
    print(f"         ContentType: {ctype}")
    print(f"         Body: {body[:300]}")
    # 检测是否返回了文字内容（可能是语音转文字结果）
    try:
        j = json.loads(body)
        if j.get("success") and j.get("data"):
            print(f"  *** SUCCESS! data={json.dumps(j['data'], ensure_ascii=False)[:500]}")
    except:
        pass
    print()

results = []

# ====================================================================
# 第一组: /open/trans/wechatAmrTrans - 穷举参数名
# ====================================================================
section("1. POST /open/trans/wechatAmrTrans - 各种参数名")

param_names = ["url", "fileUrl", "file", "voiceUrl", "amrUrl", "audioUrl",
               "mediaUrl", "filePath", "voice_url", "file_url", "amr_url",
               "audio_url", "media_url", "voiceFile", "amrFile"]

for pname in param_names:
    code, body, ctype = call_post("/open/trans/wechatAmrTrans", {pname: VOICE_URL_MP3})
    test(f"param={pname}", code, body, ctype)
    results.append({"path": "/open/trans/wechatAmrTrans", "param": pname, "code": code, "body": body[:200]})

# ====================================================================
# 第二组: 带额外参数
# ====================================================================
section("2. POST /open/trans/wechatAmrTrans - 带 wechatId/userId/msgSvrId")

combos = [
    {"url": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12"},
    {"url": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12", "userId": AID},
    {"url": VOICE_URL_MP3, "msgSvrId": "1100782783502033865"},
    {"url": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12", "userId": AID, "msgSvrId": "1100782783502033865"},
    {"fileUrl": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12"},
    {"fileUrl": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12", "userId": AID},
    {"file": VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12", "userId": AID},
]

for combo in combos:
    label = "+".join(combo.keys())
    code, body, ctype = call_post("/open/trans/wechatAmrTrans", combo)
    test(label, code, body, ctype)
    results.append({"path": "/open/trans/wechatAmrTrans", "param": label, "code": code, "body": body[:200]})

# ====================================================================
# 第三组: GET 方法
# ====================================================================
section("3. GET /open/trans/wechatAmrTrans")

for pname in ["url", "fileUrl", "file"]:
    code, body, ctype = call_get("/open/trans/wechatAmrTrans", {pname: VOICE_URL_MP3})
    test(f"GET param={pname}", code, body, ctype)

# ====================================================================
# 第四组: form-urlencoded
# ====================================================================
section("4. POST form-urlencoded /open/trans/wechatAmrTrans")

for pname in ["url", "fileUrl", "file"]:
    code, body, ctype = call_post("/open/trans/wechatAmrTrans", {pname: VOICE_URL_MP3}, "application/x-www-form-urlencoded")
    test(f"form param={pname}", code, body, ctype)

# ====================================================================
# 第五组: 其他可能的接口路径
# ====================================================================
section("5. 其他可能的接口路径")

alt_paths = [
    "/open/wechat/voiceTrans",
    "/open/wechat/voice/trans",
    "/open/trans/voice",
    "/open/trans/amrToMp3",
    "/open/trans/voiceToText",
    "/open/wechat/amrTrans",
    "/open/trans/wechatVoice",
    "/open/wechat/voiceToText",
    "/open/trans/audioToText",
    "/open/wechat/voice",
    "/open/trans/amr",
    "/open/trans/speechToText",
    "/open/wechat/speech",
    "/open/wechat/mediaToText",
]

for path in alt_paths:
    for pname in ["url", "fileUrl"]:
        data = {pname: VOICE_URL_MP3, "wechatId": "wxid_cbk7hkyyp11t12", "userId": AID}
        code, body, ctype = call_post(path, data)
        test(f"{path} param={pname}", code, body, ctype)
        results.append({"path": path, "param": pname, "code": code, "body": body[:200]})

# ====================================================================
# 第六组: 空请求看错误提示（可能泄露参数信息）
# ====================================================================
section("6. 空请求 /open/trans/wechatAmrTrans（看错误提示）")

code, body, ctype = call_post("/open/trans/wechatAmrTrans", {})
test("empty body", code, body, ctype)

code, body, ctype = call_post("/open/trans/wechatAmrTrans", None)
test("null body", code, body, ctype)

# ====================================================================
# 汇总
# ====================================================================
section("汇总")

success_count = sum(1 for r in results if '"success":true' in r["body"].lower() or '"success": true' in r["body"].lower())
ip_blocked = sum(1 for r in results if "ip" in r["body"].lower() and "无效" in r["body"])
error_count = sum(1 for r in results if r["code"] != 200)

print(f"  总测试数: {len(results)}")
print(f"  成功(success=true): {success_count}")
print(f"  IP拦截: {ip_blocked}")
print(f"  HTTP错误: {error_count}")
print()

# 输出所有非IP拦截的结果（这些是有意义的响应）
meaningful = [r for r in results if "ip" not in r["body"].lower() or "无效" not in r["body"]]
if meaningful:
    print("  有意义的响应:")
    for r in meaningful:
        print(f"    {r['path']} ({r['param']}): {r['body'][:200]}")
else:
    print("  所有请求都被IP白名单拦截")

print()
print("脚本执行完毕")
