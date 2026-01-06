# Telegram 自动加群机器人 (JQBot)

一个功能完善的 Telegram 自动加群/加频道机器人，支持多账户管理、智能加群策略和完善的统计功能。

## 功能特性

### 🏠 核心功能

- **账户管理**
  - 支持多账户管理
  - 实时状态监控（在线/离线）
  - Session 字符串导入
  - 账户列表查看和删除

- **链接管理**
  - 单个链接添加
  - 批量导入（TXT 文件）
  - 链接列表查看
  - 一键清空

- **智能加群**
  - 自定义时间间隔（随机延迟）
  - 每日加群上限设置
  - 多账户轮换
  - 支持暂停/继续/停止

- **统计面板**
  - 实时成功/失败统计
  - 成功率计算
  - 详细操作日志

## 安装部署

### 1. 环境要求

- Python 3.8+
- pip

### 2. 克隆仓库

```bash
git clone https://github.com/marinlarabel717-stack/jqbot.git
cd jqbot
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置

编辑 `jqbot.py` 文件，设置以下环境变量或直接修改代码：

```python
BOT_TOKEN = "YOUR_BOT_TOKEN"  # 从 @BotFather 获取
API_ID = 12345                 # 从 https://my.telegram.org 获取
API_HASH = "YOUR_API_HASH"     # 从 https://my.telegram.org 获取
```

或者使用环境变量：

```bash
export BOT_TOKEN="your_bot_token"
export API_ID="your_api_id"
export API_HASH="your_api_hash"
```

### 5. 运行

```bash
python jqbot.py
```

## 使用指南

### 获取 Bot Token

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建新机器人
3. 按提示设置名称和用户名
4. 获取 Token

### 获取 API_ID 和 API_HASH

1. 访问 [https://my.telegram.org](https://my.telegram.org)
2. 登录你的 Telegram 账号
3. 点击 "API development tools"
4. 创建应用并获取 `api_id` 和 `api_hash`

### 获取 Session String

使用 Telethon 生成 session string：

```python
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 12345
API_HASH = "your_api_hash"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print(client.session.save())
```

运行后登录账号，将输出的字符串复制保存。

## 操作说明

### 1. 启动机器人

在 Telegram 中找到你的机器人，发送 `/start` 启动。

### 2. 添加账户

1. 点击 `📁 账户管理`
2. 点击 `➕ 上传账户`
3. 发送 session string（文本格式）
4. 等待验证完成

### 3. 添加链接

#### 单个添加
1. 点击 `🔗 链接管理`
2. 点击 `➕ 添加链接`
3. 发送群组/频道链接

#### 批量添加
1. 点击 `🔗 链接管理`
2. 点击 `📄 上传TXT`
3. 上传包含链接的 TXT 文件（每行一个链接）

支持的链接格式：
- `https://t.me/groupname`
- `@groupname`
- `https://t.me/+invitehash`

### 4. 配置设置

1. 点击 `⚙️ 加群设置`
2. 设置时间间隔（例如：30-60 秒）
3. 设置每日上限（例如：50 个）

### 5. 开始任务

1. 点击 `🚀 开始任务`
2. 查看实时进度
3. 可随时暂停/继续/停止

### 6. 查看统计

1. 点击 `📊 统计面板` 查看今日统计
2. 点击 `📋 日志查看` 查看详细日志

## 界面预览

### 主菜单
```
🏠 主菜单

[📁 账户管理]  [🔗 链接管理]
[⚙️ 加群设置]  [🚀 开始任务]
[📊 统计面板]  [📋 日志查看]
```

### 账户管理
```
📁 账户管理

[➕ 上传账户]  [📋 账户列表]
[🗑️ 删除账户]  [🔄 刷新状态]
[🔙 返回主菜单]
```

### 任务控制
```
🚀 任务控制

状态: 运行中
进度: 15/50
失败: 2

[⏸️ 暂停]  [⏹️ 停止]
[🔙 返回主菜单]
```

## 注意事项

### ⚠️ 安全提醒

1. **保护好你的 Token 和 Session**
   - 不要分享给他人
   - 不要上传到公开仓库

2. **合理使用**
   - 设置合理的时间间隔（建议 30-60 秒）
   - 设置适当的每日上限（建议不超过 50）
   - 避免频繁操作导致账号被封

3. **账号安全**
   - 使用备用账号测试
   - 定期检查账号状态
   - 注意 Telegram 的使用条款

### 📋 常见问题

**Q: 账户添加失败？**  
A: 检查 session string 是否正确，确保 API_ID 和 API_HASH 配置正确。

**Q: 加群失败提示 FloodWait？**  
A: 说明操作过于频繁，需要等待一段时间，建议增加时间间隔。

**Q: 机器人没有响应？**  
A: 检查 Bot Token 是否正确，确保机器人正在运行。

**Q: 如何停止正在运行的任务？**  
A: 点击任务控制界面的 `⏹️ 停止` 按钮。

## 技术架构

### 依赖库

- `python-telegram-bot` - Telegram Bot API 封装
- `telethon` - Telegram MTProto 客户端
- `aiosqlite` - 异步 SQLite 数据库

### 文件结构

```
jqbot/
├── jqbot.py           # 主程序（所有功能集成）
├── requirements.txt   # Python 依赖
├── README.md          # 使用说明
├── jqbot.db          # SQLite 数据库（运行后生成）
├── sessions/         # Session 文件目录（运行后生成）
└── logs/             # 日志目录（运行后生成）
```

### 数据库结构

- **accounts** - 账户信息表
- **links** - 链接列表表
- **stats** - 操作统计表
- **settings** - 用户设置表

## 开发说明

### 代码结构

```python
# ============== 配置 ==============
# Bot Token, API credentials

# ============== 数据库 ==============
# SQLite 初始化和 CRUD 操作

# ============== 账户管理 ==============
# Session 管理、状态检查

# ============== 加群核心 ==============
# 自动加群逻辑、任务管理

# ============== 按钮定义 ==============
# InlineKeyboard 菜单定义

# ============== 回调处理 ==============
# CallbackQueryHandler 按钮点击处理

# ============== 消息处理 ==============
# 文件上传、文本输入处理

# ============== 主函数 ==============
# 启动 Bot
```

### 扩展功能

可以在现有基础上扩展：

1. **代理支持** - 添加 SOCKS5/HTTP 代理配置
2. **验证码处理** - 集成打码平台 API
3. **定时任务** - 添加定时执行功能
4. **多用户支持** - 支持多个 Bot 用户同时使用
5. **Web 面板** - 添加 Web 管理界面

## 许可证

MIT License

## 免责声明

本项目仅供学习交流使用，请勿用于违反 Telegram 服务条款的行为。使用本项目所产生的任何后果由使用者自行承担。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题或建议，请通过 GitHub Issue 联系。
