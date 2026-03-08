# S-006: 飞书集成配置指南

> 本文档列出所有需要人工在飞书后台操作的步骤。
> 完成后将获得的凭证填入服务器环境变量即可。

---

## 一、创建飞书自定义应用（用于读取表格）

### 1.1 进入飞书开放平台

1. 打开 https://open.feishu.cn/app
2. 点击右上角「创建企业自建应用」
3. 填写应用信息：
   - 应用名称：`Monica销售系统`
   - 应用描述：`读取订单表格数据，同步到销售管理系统`
   - 应用图标：随意
4. 点击「确认创建」

### 1.2 记录App凭证

创建完成后，在「凭证与基础信息」页面记录：
- **App ID** → 环境变量 `FEISHU_APP_ID`
- **App Secret** → 环境变量 `FEISHU_APP_SECRET`

### 1.3 配置应用权限

进入「权限管理」→「API 权限」，搜索并开通以下权限：

| 权限名称 | 权限标识 | 用途 |
|----------|---------|------|
| 查看、评论和导出电子表格 | `sheets:spreadsheet:readonly` | 读取订单表格 |
| 查看电子表格 | `sheets:spreadsheet` | 读取表格元数据 |

### 1.4 发布应用

1. 进入「版本管理与发布」
2. 点击「创建版本」
3. 填写版本号（如 1.0.0）和更新说明
4. 点击「申请发布」
5. **管理员审批**：需要飞书管理员在后台审批通过

### 1.5 授权应用访问表格

应用发布后，需要将表格授权给应用：
1. 打开飞书订单表格
2. 点击右上角「...」→「更多」→「添加文档应用」
3. 搜索并添加「Monica销售系统」应用
4. 授予「可阅读」权限

---

## 二、获取飞书表格Token

### 2.1 从URL获取

打开飞书订单表格，URL格式如下：
```
https://xxx.feishu.cn/sheets/{spreadsheet_token}
```

例如：
```
https://abc.feishu.cn/sheets/shtcnxxxxxxxxxxxxxx
```

其中 `shtcnxxxxxxxxxxxxxx` 就是 **spreadsheet_token**。

→ 环境变量 `FEISHU_SPREADSHEET_TOKEN`

### 2.2 工作表ID（可选）

如果表格有多个sheet，需要指定同步哪个：
1. 打开表格
2. 底部sheet标签名就是工作表名称
3. 可以通过脚本 `--dry-run` 模式自动获取第一个sheet

如果不设置，脚本会自动使用第一个工作表。

→ 环境变量 `FEISHU_SHEET_ID`（可选）

---

## 三、创建飞书自定义机器人（用于推送通知）

### 3.1 在群聊中添加机器人

1. 打开要接收通知的飞书群聊（建议创建专门的「销售系统通知」群）
2. 点击群设置（右上角齿轮图标）
3. 选择「群机器人」→「添加机器人」
4. 选择「自定义机器人」
5. 填写机器人名称：`Monica销售助手`
6. 填写描述：`推送每日跟进任务和系统告警`

### 3.2 记录Webhook地址

创建完成后会显示 Webhook 地址，格式如下：
```
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

→ 环境变量 `FEISHU_WEBHOOK_URL`

### 3.3 安全设置（可选）

建议开启「签名校验」增强安全性：
1. 在机器人设置中开启签名校验
2. 记录签名密钥
3. 如果开启签名，需在脚本中额外实现签名逻辑（当前版本未实现，建议暂不开启）

---

## 四、确认飞书订单表格结构

脚本预期的表格列结构如下，请确认实际表格是否匹配：

| 列号 | 预期内容 | 说明 |
|------|---------|------|
| A列 | 客户微信号 | **必填**，用于关联contacts表 |
| B列 | 客户姓名/备注名 | 仅日志使用，不入库 |
| C列 | 下单日期 | **必填**，支持 2026-03-08、2026/03/08 等格式 |
| D列 | 订单金额（元） | 数字，可含逗号和¥符号 |
| E列 | 产品线 | 如：沙发、床、柜子 |
| F列 | 负责销售 | 销售名称（可欣/小杰/霄剑/Fiona/晴天喵/Joy） |
| G列 | 备注 | 可选 |

**第一行必须是表头**，脚本会自动跳过。

如果实际表格列顺序不同，需修改 `feishu_sync_orders.py` 中的 `COLUMN_MAP` 配置。

---

## 五、服务器配置

### 5.1 设置环境变量

SSH登录阿里云服务器：
```bash
ssh admin@119.23.44.77
```

编辑环境变量文件：
```bash
nano ~/.bashrc
```

在文件末尾添加：
```bash
# 飞书集成 (S-006)
export FEISHU_APP_ID="cli_xxxxxxxxxx"
export FEISHU_APP_SECRET="xxxxxxxxxxxxxxxxxx"
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export FEISHU_SPREADSHEET_TOKEN="shtcnxxxxxxxxxxxxxx"
# export FEISHU_SHEET_ID=""  # 可选，不设则用第一个sheet
```

生效：
```bash
source ~/.bashrc
```

### 5.2 安装Python依赖

```bash
pip3 install requests supabase
```
（requests和supabase通常已安装，如果已有则跳过）

### 5.3 部署脚本

```bash
cd /home/admin/monica-scripts/
# 从GitHub拉取最新代码
git pull

# 或手动复制
# scp scripts/feishu_notify.py admin@119.23.44.77:/home/admin/monica-scripts/
# scp scripts/feishu_sync_orders.py admin@119.23.44.77:/home/admin/monica-scripts/
```

### 5.4 执行orders表SQL迁移

在Supabase SQL编辑器中执行 `sql/s006_orders_table.sql`。

### 5.5 测试运行

```bash
# 测试飞书推送（dry-run，不实际发送）
python3 feishu_notify.py --dry-run

# 测试飞书推送（实际发送）
python3 feishu_notify.py

# 测试订单同步（dry-run，不写入数据库）
python3 feishu_sync_orders.py --dry-run

# 正式同步
python3 feishu_sync_orders.py
```

### 5.6 配置Cron定时任务

```bash
crontab -e
```

添加以下内容：
```bash
# S-006: 飞书每日任务推送（每天早上8:00）
# 先生成任务(6:00已有)，再推送通知
0 8 * * * cd /home/admin/monica-scripts && python3 feishu_notify.py >> /var/log/monica/feishu_notify.log 2>&1

# S-006: 飞书订单同步（每天中午12:00）
0 12 * * * cd /home/admin/monica-scripts && python3 feishu_sync_orders.py >> /var/log/monica/feishu_sync_orders.log 2>&1
```

创建日志目录（如果不存在）：
```bash
mkdir -p /var/log/monica/
```

---

## 六、完整操作清单（Checklist）

按顺序完成以下步骤：

- [ ] **步骤1**：在飞书开放平台创建企业自建应用「Monica销售系统」
- [ ] **步骤2**：记录 App ID 和 App Secret
- [ ] **步骤3**：开通 `sheets:spreadsheet:readonly` 和 `sheets:spreadsheet` 权限
- [ ] **步骤4**：发布应用版本，管理员审批
- [ ] **步骤5**：将应用添加到订单表格的文档应用中（授予可阅读权限）
- [ ] **步骤6**：从订单表格URL获取 spreadsheet_token
- [ ] **步骤7**：确认订单表格列结构与预期一致（见第四节），如不一致告知调整
- [ ] **步骤8**：创建飞书群「销售系统通知」，添加自定义机器人
- [ ] **步骤9**：记录机器人 Webhook URL
- [ ] **步骤10**：在Supabase执行 `sql/s006_orders_table.sql` 创建orders表
- [ ] **步骤11**：在服务器 `~/.bashrc` 中配置4个环境变量
- [ ] **步骤12**：部署脚本到 `/home/admin/monica-scripts/`
- [ ] **步骤13**：`python3 feishu_notify.py --dry-run` 测试推送
- [ ] **步骤14**：`python3 feishu_sync_orders.py --dry-run` 测试同步
- [ ] **步骤15**：配置cron定时任务

---

## 七、常见问题

### Q: 获取token报错 "app not found"
飞书应用未发布或未审批通过。检查应用状态。

### Q: 读取表格报错 "permission denied"
应用未被授权访问该表格。需要在表格的「文档应用」中添加应用。

### Q: 订单同步后数据不对
1. 检查表格列顺序是否与 `COLUMN_MAP` 一致
2. 检查日期格式是否被正确解析
3. 用 `--dry-run` 模式预览解析结果

### Q: Webhook推送没收到消息
1. 检查 `FEISHU_WEBHOOK_URL` 是否正确
2. 检查机器人是否被移出群聊
3. 查看 `/var/log/monica/feishu_notify.log` 日志
