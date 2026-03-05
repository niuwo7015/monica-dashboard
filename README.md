# Monica 销售AI系统

莫妮卡摩卡高定家具的AI驱动CRM和销售辅助平台。

## 目录结构

```
├── src/                    # 前端源码
│   ├── lib/                # 公共库（Supabase客户端等）
│   └── pages/              # 页面组件
├── scripts/                # 服务器端脚本
│   ├── yunke_pull_chat.py   # 云客聊天记录增量拉取
│   ├── yunke_pull_friends.py # 云客好友列表同步
│   ├── yunke_backfill.py    # 历史数据回补
│   ├── git_push.sh          # 自动git推送
│   └── crontab_config.txt   # 定时任务配置
├── sql/                    # 数据库变更SQL
│   └── phase0_schema_changes.sql
├── index.html              # 主仪表盘页面
└── .env.example            # 环境变量模板
```

## 技术栈

- **前端**: React + Vite + Tailwind CSS
- **后端/数据库**: Supabase (PostgreSQL)
- **部署**: Vercel (前端) + 阿里云轻量服务器 (脚本)
- **数据源**: 云客API (微信聊天记录与好友列表)

## 环境变量

参考 `.env.example` 配置所需的环境变量。注意：`SUPABASE_SERVICE_ROLE_KEY` 仅用于服务器端脚本，不要提交到代码仓库。
