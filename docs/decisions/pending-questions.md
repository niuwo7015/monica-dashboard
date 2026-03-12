# L-003 待人工操作项 + 执行状态

> 生成时间: 2026-03-09

---

## 已完成项 ✅

### 1. 云客API文档深度阅读 ✅
- 阅读了基础版和高级版全部微信模块文档
- 9个核心问题全部回答，详见 `yunke_api_full_reference.md`
- **最重要发现：应该用allRecords替代records，不需要按好友逐个拉取**

### 2. 飞书权限开通 ✅
- `sheets:spreadsheet` (编辑和管理电子表格) — **已开通**
- `sheets:spreadsheet:readonly` (查看和导出电子表格) — **已开通**

---

## 需要你人工完成的操作 🔧

### 3. 获取飞书App Secret
- 位置：https://open.feishu.cn/app/cli_a927246f00b85bb4/baseinfo
- App Secret旁有眼睛图标，点击显示并复制
- App ID: `cli_a927246f00b85bb4`

### 4. 创建飞书应用版本并发布
- 位置：https://open.feishu.cn/app/cli_a927246f00b85bb4/version
- 当前状态：**待上线**
- 步骤：点"创建版本" → 填版本号 → 提交发布
- 发布后权限配置才生效

### 5. 服务器配环境变量
- SSH: `ssh -i ~/.ssh/aliyun_jst admin@119.23.44.77`
- 设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET
- 注意：S-005在跑（PID 72861），不要重启

### 6. SQL迁移 + dry-run
- Supabase SQL编辑器已打开
- 需要确认迁移脚本内容

---

## 🔥 紧急建议：切换到allRecords接口
当前S-005用records按好友逐个拉（36小时），改用allRecords后：
- 不需要好友列表，按公司维度拉全量
- 5秒/次，不限条数
- 预计12小时内完成，实际可能更快
- records场景2限频是2秒不是10秒（S-004是对的）