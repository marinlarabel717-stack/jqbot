#开发一个自动加群，加频道得 机器人 
#上传session/tdata账户
#上传群链接或者txt文件
#自动加群，自定义配置金间隔
#自动加群后如需机器人验证，自动过验证
"""
Telegram 自动加群机器人 - 单文件版本
功能：上传session/tdata、上传群链接/txt、自定义间隔、自动过验证
"""

import os
import re
import json
import shutil
import sqlite3
import asyncio
import random
import logging
import zipfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    ContextTypes, 
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import (
    FloodWaitError, 
    ChannelPrivateError,
    UserAlreadyParticipantError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserBannedInChannelError
)

# ==================== 配置 ====================
API_ID = 12345678  # 从 my.telegram.org 获取
API_HASH = "your_api_hash_here"  # 从 my.telegram.org 获取
BOT_TOKEN = "your_bot_token_here"  # 从 @BotFather 获取

# 数据目录
DATA_DIR = "data"
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

# 默认配置
DEFAULT_CONFIG = {
    "min_interval":  30,
    "max_interval":  60,
    "daily_limit":  25,
    "auto_verify": True,
}

# 创建目录
for d in [DATA_DIR, SESSIONS_DIR, UPLOADS_DIR]: 
    os.makedirs(d, exist_ok=True)

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 对话状态
(
    WAITING_SESSION_FILE,
    WAITING_STRING_SESSION,
    WAITING_TDATA,
    WAITING_LINKS,
    WAITING_TXT_FILE,
    WAITING_INTERVAL,
    WAITING_LIMIT,
) = range(7)

# 全局存储
user_tasks = {}  # 用户任务状态
clients = {}  # Telethon 客户端
pending_logins = {}  # 待验证登录

# ==================== 数据库 ====================
def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            config TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            session_path TEXT,
            account_type TEXT,
            status TEXT DEFAULT 'active',
            daily_joined INTEGER DEFAULT 0,
            last_join_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetch=False):
    """执行数据库操作"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = cursor.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return result

def get_or_create_user(user_id, username=None):
    """获取或创建用户"""
    result = db_execute("SELECT * FROM users WHERE user_id = ? ", (user_id,), fetch=True)
    if not result:
        db_execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))

def get_user_config(user_id):
    """获取用户配置"""
    result = db_execute("SELECT config FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if result and result[0][0]:
        return json.loads(result[0][0])
    return {}

def update_user_config(user_id, config):
    """更新用户配置"""
    db_execute("UPDATE users SET config = ? WHERE user_id = ?", (json.dumps(config), user_id))

def add_account(user_id, phone, session_path, account_type):
    """添加账号"""
    db_execute(
        "INSERT INTO accounts (user_id, phone, session_path, account_type) VALUES (?, ?, ?, ?)",
        (user_id, phone, session_path, account_type)
    )

def get_user_accounts(user_id):
    """获取用户账号列表"""
    return db_execute(
        "SELECT * FROM accounts WHERE user_id = ?  AND status = 'active'",
        (user_id,), fetch=True
    ) or []

def update_account_daily_count(account_id):
    """更新账号每日加群计数"""
    today = str(datetime.now().date())
    result = db_execute(
        "SELECT last_join_date, daily_joined FROM accounts WHERE id = ?",
        (account_id,), fetch=True
    )
    if result: 
        last_date, count = result[0]
        new_count = count + 1 if last_date == today else 1
        db_execute(
            "UPDATE accounts SET daily_joined = ?, last_join_date = ?  WHERE id = ?",
            (new_count, today, account_id)
        )
        return new_count
    return 0

# ==================== 键盘 ====================
def main_menu_kb():
    """主菜单"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 账号管理", callback_data='accounts')],
        [InlineKeyboardButton("➕ 开始加群", callback_data='join')],
        [InlineKeyboardButton("⚙️ 配置设置", callback_data='settings')],
        [InlineKeyboardButton("📊 任务状态", callback_data='status')],
        [InlineKeyboardButton("❓ 使用帮助", callback_data='help')],
    ])

def account_menu_kb():
    """账号管理菜单"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 上传 Session 文件", callback_data='upload_session')],
        [InlineKeyboardButton("📝 输入 StringSession", callback_data='input_session')],
        [InlineKeyboardButton("📁 上传 TData (ZIP)", callback_data='upload_tdata')],
        [InlineKeyboardButton("📋 查看我的账号", callback_data='list_accounts')],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
    ])

def join_menu_kb(accounts):
    """选择账号菜单"""
    keyboard = []
    for acc in accounts:
        acc_id, _, phone, _, acc_type, _, daily_joined, *_ = acc
        btn_text = f"📱 {phone} ({acc_type}) - 今日:  {daily_joined}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'sel_acc_{acc_id}')])
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

def link_input_kb():
    """链接输入方式"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 直接输入链接", callback_data='input_links')],
        [InlineKeyboardButton("📄 上传 TXT 文件", callback_data='upload_txt')],
        [InlineKeyboardButton("🔙 返回", callback_data='join')],
    ])

def settings_kb(config):
    """设置菜单"""
    verify_status = "✅" if config. get('auto_verify', True) else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ 间隔: {config.get('min_interval', 30)}-{config.get('max_interval', 60)}秒", callback_data='set_interval')],
        [InlineKeyboardButton(f"📊 每日上限: {config.get('daily_limit', 25)}", callback_data='set_limit')],
        [InlineKeyboardButton(f"🤖 自动过验证: {verify_status}", callback_data='toggle_verify')],
        [InlineKeyboardButton("🔄 重置为默认", callback_data='reset_config')],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
    ])

def confirm_kb():
    """确认键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认开始", callback_data='confirm'),
         InlineKeyboardButton("❌ 取消", callback_data='cancel')]
    ])

def stop_kb():
    """停止任务键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ 停止任务", callback_data='stop_task')]
    ])

# ==================== 账号管理 ====================
async def load_session_file(user_id, file_path):
    """从 session 文件加载账号"""
    try:
        filename = f"{user_id}_{datetime.now().timestamp()}.session"
        dest_path = os.path.join(SESSIONS_DIR, filename)
        shutil.copy(file_path, dest_path)
        
        session_name = dest_path.replace('.session', '')
        client = TelegramClient(session_name, API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            os.remove(dest_path)
            return {"success": False, "error": "Session 已过期或无效"}
        
        me = await client.get_me()
        phone = me.phone or "未知"
        await client.disconnect()
        
        return {"success": True, "phone": phone, "session_path": dest_path, "type": "session"}
    except Exception as e:
        return {"success": False, "error":  str(e)}

async def load_string_session(user_id, session_string):
    """从 StringSession 加载账号"""
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"success": False, "error": "Session 已过期或无效"}
        
        me = await client.get_me()
        phone = me.phone or "未知"
        
        # 保存为文件
        filename = f"{user_id}_{phone. replace('+', '')}_{datetime.now().timestamp()}"
        dest_path = os. path.join(SESSIONS_DIR, filename)
        
        new_client = TelegramClient(dest_path, API_ID, API_HASH)
        new_client.session. set_dc(client.session.dc_id, client.session.server_address, client.session.port)
        new_client.session.auth_key = client.session.auth_key
        new_client. session.save()
        
        await client.disconnect()
        
        return {"success": True, "phone":  phone, "session_path": dest_path + ".session", "type": "session"}
    except Exception as e: 
        return {"success": False, "error": str(e)}

async def load_tdata_zip(user_id, zip_path):
    """从 TData ZIP 加载账号"""
    try:
        extract_dir = os.path.join(UPLOADS_DIR, f"{user_id}_tdata")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # 这里需要 opentele 库来转换 tdata
        # 简化处理：提示用户使用其他方式
        shutil.rmtree(extract_dir, ignore_errors=True)
        return {
            "success": False, 
            "error": "TData 转换需要额外依赖，建议使用 Session 文件或 StringSession"
        }
    except Exception as e:
        return {"success": False, "error":  str(e)}

async def get_client(account_id, session_path):
    """获取 Telethon 客户端"""
    if account_id in clients:
        client = clients[account_id]
        if client.is_connected():
            return client
    
    session_name = session_path.replace('.session', '')
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        clients[account_id] = client
        return client
    return None

# ==================== 自动验证 ====================
class AutoVerifier:
    """自动过验证"""
    
    VERIFY_KEYWORDS = ['验证', 'verify', 'captcha', '点击', 'click', 'press', '按钮', 'button', '人机', 'human', 'robot']
    
    def __init__(self, client):
        self.client = client
    
    async def setup(self):
        """设置消息监听"""
        @self.client.on(events. NewMessage(incoming=True))
        async def handler(event):
            await self.handle_message(event)
    
    async def handle_message(self, event):
        """处理验证消息"""
        message = event.message
        text = (message.text or '').lower()
        
        # 检查是否是验证消息
        is_verify = any(kw in text for kw in self.VERIFY_KEYWORDS)
        
        if is_verify or message.buttons:
            await self.solve(message, event)
    
    async def solve(self, message, event):
        """解决验证"""
        text = message.text or ''
        
        # 1. 按钮验证
        if message.buttons:
            await self.solve_button(message)
            return
        
        # 2. 数学验证
        math_result = self.solve_math(text)
        if math_result is not None:
            await asyncio.sleep(1)
            await event.respond(str(math_result))
            return
    
    async def solve_button(self, message):
        """解决按钮验证"""
        try:
            buttons = message.buttons
            if not buttons:
                return
            
            # 优先文字
            priority = ['验证', 'verify', '不是机器人', 'not a robot', 'human', '确认', 'confirm', '进入', 'enter', 'start', '开始']
            
            for row in buttons:
                for btn in row:
                    btn_text = (btn.text or '').lower()
                    if any(p in btn_text for p in priority):
                        await asyncio.sleep(0.5)
                        await btn.click()
                        return
            
            # 点击第一个按钮
            if buttons[0]: 
                await asyncio.sleep(0.5)
                await buttons[0][0].click()
        except Exception as e:
            logger.error(f"按钮验证失败: {e}")
    
    def solve_math(self, text):
        """解决数学验证"""
        patterns = [
            (r'(\d+)\s*[\+\＋]\s*(\d+)', lambda a, b: a + b),
            (r'(\d+)\s*[\-\－]\s*(\d+)', lambda a, b: a - b),
            (r'(\d+)\s*[\*\×\x]\s*(\d+)', lambda a, b: a * b),
        ]
        
        for pattern, func in patterns:
            match = re.search(pattern, text)
            if match:
                a, b = int(match.group(1)), int(match.group(2))
                return func(a, b)
        return None

# ==================== 加群核心 ====================
class GroupJoiner:
    """加群器"""
    
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.verifier = None
        self.running = False
        self.stats = {"success": 0, "failed": 0, "skipped": 0}
    
    async def start(self):
        """启动"""
        if self.config.get('auto_verify', True):
            self.verifier = AutoVerifier(self.client)
            await self.verifier. setup()
        self.running = True
    
    def stop(self):
        """停止"""
        self.running = False
    
    def parse_link(self, link):
        """解析链接"""
        link = link.strip()
        
        # 私有链接
        for pattern in [r't\. me/\+([a-zA-Z0-9_-]+)', r't\.me/joinchat/([a-zA-Z0-9_-]+)']:
            match = re.search(pattern, link)
            if match:
                return {"type": "private", "hash": match.group(1)}
        
        # 公开链接
        for pattern in [r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})', r'^@? ([a-zA-Z][a-zA-Z0-9_]{3,})$']:
            match = re.search(pattern, link)
            if match:
                username = match.group(1)
                if username. lower() not in ['joinchat', 'addstickers', 'share']: 
                    return {"type": "public", "username": username}
        
        return {"type": "unknown"}
    
    async def join_one(self, link):
        """加入单个群组"""
        result = {"link": link, "success": False, "message": ""}
        parsed = self.parse_link(link)
        
        try:
            if parsed["type"] == "private":
                try:
                    await self.client(CheckChatInviteRequest(parsed["hash"]))
                except (InviteHashExpiredError, InviteHashInvalidError) as e:
                    result["message"] = "邀请链接无效或已过期"
                    return result
                
                await self.client(ImportChatInviteRequest(parsed["hash"]))
                result["success"] = True
                result["message"] = "成功加入私有群组"
                
            elif parsed["type"] == "public":
                await self.client(JoinChannelRequest(parsed["username"]))
                result["success"] = True
                result["message"] = "成功加入公开群组"
            else:
                result["message"] = "无法识别的链接格式"
                
        except UserAlreadyParticipantError:
            result["success"] = True
            result["message"] = "已在群组中"
            self.stats["skipped"] += 1
            return result
        except FloodWaitError as e:
            result["message"] = f"触发限制，需等待 {e.seconds} 秒"
            if e.seconds < 120:
                await asyncio.sleep(e.seconds + 5)
                return await self.join_one(link)
        except ChannelPrivateError:
            result["message"] = "群组是私有的"
        except UserBannedInChannelError:
            result["message"] = "账号被该群组封禁"
        except Exception as e:
            result["message"] = f"失败: {str(e)[:50]}"
        
        if result["success"]:
            self. stats["success"] += 1
        else:
            self.stats["failed"] += 1
        
        return result
    
    async def join_batch(self, links, progress_cb=None):
        """批量加入"""
        results = []
        total = len(links)
        
        for i, link in enumerate(links):
            if not self.running:
                break
            
            result = await self.join_one(link)
            results.append(result)
            
            if progress_cb:
                await progress_cb(i + 1, total, result)
            
            # 验证等待
            if result["success"] and self.config.get('auto_verify'):
                await asyncio.sleep(3)
            
            # 间隔
            if i < total - 1:
                interval = random.randint(
                    self.config.get('min_interval', 30),
                    self.config.get('max_interval', 60)
                )
                await asyncio.sleep(interval)
        
        return results

# ==================== Bot 处理器 ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令"""
    user = update.effective_user
    get_or_create_user(user. id, user.username)
    
    await update.message.reply_text(
        f"👋 欢迎使用 **Telegram 自动加群助手**!\n\n"
        f"🆔 用户ID: `{user.id}`\n\n"
        "**功能:**\n"
        "📱 支持 Session / StringSession\n"
        "📝 支持输入链接或上传 TXT\n"
        "⚙️ 自定义加群间隔\n"
        "🤖 自动过验证机器人\n\n"
        "请选择操作:",
        reply_markup=main_menu_kb(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按钮回调处理"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # 主菜单
    if data == 'main_menu':
        await query.edit_message_text("请选择操作:", reply_markup=main_menu_kb())
        return ConversationHandler.END
    
    # 账号管理
    elif data == 'accounts':
        await query.edit_message_text(
            "📱 **账号管理**\n\n选择上传方式:",
            reply_markup=account_menu_kb(),
            parse_mode='Markdown'
        )
    
    elif data == 'upload_session':
        await query.edit_message_text(
            "📤 **上传 Session 文件**\n\n"
            "请发送 `.session` 文件\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_SESSION_FILE
    
    elif data == 'input_session':
        await query.edit_message_text(
            "📝 **输入 StringSession**\n\n"
            "请发送 StringSession 字符串\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_STRING_SESSION
    
    elif data == 'upload_tdata': 
        await query.edit_message_text(
            "📁 **上传 TData**\n\n"
            "请将 tdata 文件夹打包成 ZIP 发送\n\n"
            "⚠️ 建议使用 Session 文件方式\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_TDATA
    
    elif data == 'list_accounts':
        accounts = get_user_accounts(user_id)
        if not accounts:
            text = "📋 **我的账号**\n\n暂无绑定账号"
        else:
            text = "📋 **我的账号**\n\n"
            for acc in accounts:
                acc_id, _, phone, _, acc_type, status, daily, *_ = acc
                emoji = "✅" if status == 'active' else "❌"
                text += f"{emoji} `{phone}` ({acc_type}) - 今日:  {daily}\n"
        
        await query.edit_message_text(text, reply_markup=account_menu_kb(), parse_mode='Markdown')
    
    # 加群
    elif data == 'join': 
        accounts = get_user_accounts(user_id)
        if not accounts:
            await query.edit_message_text(
                "❌ 请先在「账号管理」中添加账号",
                reply_markup=main_menu_kb()
            )
            return ConversationHandler.END
        
        await query.edit_message_text(
            "➕ **开始加群**\n\n请选择账号:",
            reply_markup=join_menu_kb(accounts),
            parse_mode='Markdown'
        )
    
    elif data. startswith('sel_acc_'):
        account_id = int(data.split('_')[-1])
        context.user_data['account_id'] = account_id
        await query.edit_message_text(
            "📝 **输入群组链接**\n\n请选择方式:",
            reply_markup=link_input_kb(),
            parse_mode='Markdown'
        )
    
    elif data == 'input_links':
        await query.edit_message_text(
            "📝 **输入群组链接**\n\n"
            "请发送链接，每行一个\n\n"
            "支持格式:\n"
            "• `https://t.me/username`\n"
            "• `https://t.me/+invitehash`\n"
            "• `@username`\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_LINKS
    
    elif data == 'upload_txt':
        await query.edit_message_text(
            "📄 **上传链接文件**\n\n"
            "请发送 TXT 文件，每行一个链接\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_TXT_FILE
    
    # 设置
    elif data == 'settings':
        config = {**DEFAULT_CONFIG, **get_user_config(user_id)}
        await query.edit_message_text(
            "⚙️ **配置设置**\n\n"
            f"• 加群间隔: {config['min_interval']}-{config['max_interval']} 秒\n"
            f"• 每日上限: {config['daily_limit']} 个\n"
            f"• 自动验证: {'开启' if config['auto_verify'] else '关闭'}",
            reply_markup=settings_kb(config),
            parse_mode='Markdown'
        )
    
    elif data == 'set_interval':
        await query.edit_message_text(
            "⏱ **设置间隔**\n\n"
            "请输入格式: `最小-最大`\n"
            "例如: `30-60`\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_INTERVAL
    
    elif data == 'set_limit':
        await query.edit_message_text(
            "📊 **设置每日上限**\n\n"
            "请输入数字 (1-100)\n"
            "例如: `25`\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )
        return WAITING_LIMIT
    
    elif data == 'toggle_verify':
        config = get_user_config(user_id)
        config['auto_verify'] = not config.get('auto_verify', True)
        update_user_config(user_id, config)
        merged = {**DEFAULT_CONFIG, **config}
        await query.edit_message_text(
            f"✅ 自动验证已{'开启' if config['auto_verify'] else '关闭'}",
            reply_markup=settings_kb(merged),
            parse_mode='Markdown'
        )
    
    elif data == 'reset_config':
        update_user_config(user_id, {})
        await query.edit_message_text(
            "✅ 已重置为默认配置",
            reply_markup=settings_kb(DEFAULT_CONFIG),
            parse_mode='Markdown'
        )
    
    # 任务状态
    elif data == 'status':
        task = user_tasks.get(user_id)
        if task and task.get('running'):
            stats = task. get('stats', {})
            text = (
                f"📊 **任务状态**\n\n"
                f"状态: 🟢 运行中\n"
                f"进度: {task. get('current', 0)}/{task.get('total', 0)}\n"
                f"成功: {stats.get('success', 0)}\n"
                f"失败: {stats.get('failed', 0)}"
            )
            kb = stop_kb()
        else:
            text = "📊 **任务状态**\n\n当前没有运行中的任务"
            kb = main_menu_kb()
        
        await query.edit_message_text(text, reply_markup=kb, parse_mode='Markdown')
    
    elif data == 'stop_task':
        task = user_tasks.get(user_id)
        if task and task.get('joiner'):
            task['joiner']. stop()
            task['running'] = False
        await query.edit_message_text("⏹ 任务已停止", reply_markup=main_menu_kb())
    
    # 帮助
    elif data == 'help':
        await query.edit_message_text(
            "❓ **使用帮助**\n\n"
            "**1.  绑定账号**\n"
            "• 上传 `.session` 文件\n"
            "• 输入 StringSession\n\n"
            "**2. 添加群组链接**\n"
            "• 直接发送链接（每行一个）\n"
            "• 上传 TXT 文件\n\n"
            "**3. 配置建议**\n"
            "• 间隔: 30-60秒\n"
            "• 每日上限: 不超过30\n\n"
            "**4. 注意事项**\n"
            "⚠️ 频繁加群可能被限制\n"
            "⚠️ 建议使用小号\n",
            reply_markup=main_menu_kb(),
            parse_mode='Markdown'
        )
    
    return ConversationHandler.END

# ==================== 消息处理 ====================
async def receive_session_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收 session 文件"""
    user_id = update.effective_user.id
    doc = update.message.document
    
    if not doc. file_name.endswith('.session'):
        await update.message.reply_text("❌ 请发送 .session 文件")
        return WAITING_SESSION_FILE
    
    await update.message.reply_text("⏳ 正在验证...")
    
    file = await doc.get_file()
    file_path = os.path.join(UPLOADS_DIR, f"{user_id}_{doc.file_name}")
    await file.download_to_drive(file_path)
    
    result = await load_session_file(user_id, file_path)
    os.remove(file_path)
    
    if result['success']:
        add_account(user_id, result['phone'], result['session_path'], result['type'])
        await update.message. reply_text(
            f"✅ 绑定成功!\n手机号: `{result['phone']}`",
            reply_markup=main_menu_kb(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ 失败: {result['error']}", reply_markup=account_menu_kb())
    
    return ConversationHandler.END

async def receive_string_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收 StringSession"""
    user_id = update. effective_user.id
    session_str = update.message.text. strip()
    
    await update.message.reply_text("⏳ 正在验证...")
    
    result = await load_string_session(user_id, session_str)
    
    if result['success']:
        add_account(user_id, result['phone'], result['session_path'], result['type'])
        await update.message. reply_text(
            f"✅ 绑定成功!\n手机号: `{result['phone']}`",
            reply_markup=main_menu_kb(),
            parse_mode='Markdown'
        )
    else:
        await update. message.reply_text(f"❌ 失败: {result['error']}", reply_markup=account_menu_kb())
    
    return ConversationHandler.END

async def receive_tdata(update: Update, context:  ContextTypes.DEFAULT_TYPE):
    """接收 TData ZIP"""
    user_id = update. effective_user.id
    doc = update.message.document
    
    if not doc.file_name.endswith('.zip'):
        await update.message. reply_text("❌ 请发送 ZIP 文件")
        return WAITING_TDATA
    
    await update.message.reply_text("⏳ 正在处理...")
    
    file = await doc.get_file()
    file_path = os.path.join(UPLOADS_DIR, f"{user_id}_tdata.zip")
    await file.download_to_drive(file_path)
    
    result = await load_tdata_zip(user_id, file_path)
    os.remove(file_path)
    
    if result['success']:
        add_account(user_id, result['phone'], result['session_path'], 'tdata')
        await update.message.reply_text(
            f"✅ 绑定成功!\n手机号: `{result['phone']}`",
            reply_markup=main_menu_kb(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ 失败: {result['error']}", reply_markup=account_menu_kb())
    
    return ConversationHandler.END

async def receive_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收群组链接"""
    text = update.message.text. strip()
    links = [l.strip() for l in text.split('\n') if l.strip()]
    
    if not links:
        await update.message. reply_text("❌ 未检测到有效链接")
        return WAITING_LINKS
    
    context.user_data['links'] = links
    await update.message. reply_text(
        f"📝 检测到 **{len(links)}** 个链接\n\n确认开始加群? ",
        reply_markup=confirm_kb(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def receive_txt_file(update: Update, context:  ContextTypes.DEFAULT_TYPE):
    """接收 TXT 文件"""
    user_id = update.effective_user. id
    doc = update.message.document
    
    if not doc.file_name.endswith('.txt'):
        await update. message.reply_text("❌ 请发送 . txt 文件")
        return WAITING_TXT_FILE
    
    file = await doc.get_file()
    file_path = os. path.join(UPLOADS_DIR, f"{user_id}_links.txt")
    await file.download_to_drive(file_path)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        links = [l.strip() for l in f.readlines() if l.strip()]
    
    os.remove(file_path)
    
    if not links: 
        await update.message.reply_text("❌ 文件中未检测到链接")
        return WAITING_TXT_FILE
    
    context.user_data['links'] = links
    await update.message.reply_text(
        f"📝 检测到 **{len(links)}** 个链接\n\n确认开始加群?",
        reply_markup=confirm_kb(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def receive_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收间隔设置"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    try:
        min_v, max_v = map(int, text.split('-'))
        if min_v < 5 or max_v < min_v:
            raise ValueError()
        
        config = get_user_config(user_id)
        config['min_interval'] = min_v
        config['max_interval'] = max_v
        update_user_config(user_id, config)
        
        await update.message.reply_text(
            f"✅ 间隔已设为 {min_v}-{max_v} 秒",
            reply_markup=main_menu_kb()
        )
    except:
        await update.message.reply_text("❌ 格式错误，请输入如:  30-60")
        return WAITING_INTERVAL
    
    return ConversationHandler. END

async def receive_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收限制设置"""
    user_id = update.effective_user. id
    text = update.message.text.strip()
    
    try:
        limit = int(text)
        if limit < 1 or limit > 100:
            raise ValueError()
        
        config = get_user_config(user_id)
        config['daily_limit'] = limit
        update_user_config(user_id, config)
        
        await update.message.reply_text(f"✅ 每日上限已设为 {limit}", reply_markup=main_menu_kb())
    except:
        await update.message.reply_text("❌ 请输入1-100之间的数字")
        return WAITING_LIMIT
    
    return ConversationHandler.END

async def confirm_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认开始任务"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel':
        await query.edit_message_text("❌ 已取消", reply_markup=main_menu_kb())
        return
    
    user_id = update.effective_user.id
    account_id = context.user_data.get('account_id')
    links = context.user_data.get('links', [])
    
    if not account_id or not links:
        await query. edit_message_text("❌ 参数错误", reply_markup=main_menu_kb())
        return
    
    # 获取账号
    accounts = get_user_accounts(user_id)
    account = next((a for a in accounts if a[0] == account_id), None)
    
    if not account:
        await query.edit_message_text("❌ 账号不存在", reply_markup=main_menu_kb())
        return
    
    session_path = account[3]
    config = {**DEFAULT_CONFIG, **get_user_config(user_id)}
    
    # 获取客户端
    client = await get_client(account_id, session_path)
    if not client:
        await query. edit_message_text("❌ 账号登录失败", reply_markup=main_menu_kb())
        return
    
    # 创建加群器
    joiner = GroupJoiner(client, config)
    await joiner.start()
    
    user_tasks[user_id] = {
        'running': True,
        'joiner': joiner,
        'total': len(links),
        'current': 0,
        'stats': {}
    }
    
    async def progress_cb(current, total, result):
        user_tasks[user_id]['current'] = current
        user_tasks[user_id]['stats'] = joiner.stats
        if result['success']:
            update_account_daily_count(account_id)
    
    await query.edit_message_text(
        f"🚀 **任务开始**\n\n"
        f"账号: `{account[2]}`\n"
        f"链接: {len(links)} 个\n"
        f"间隔: {config['min_interval']}-{config['max_interval']}秒\n\n"
        f"⏳ 执行中...",
        reply_markup=stop_kb(),
        parse_mode='Markdown'
    )
    
    # 执行任务
    results = await joiner.join_batch(links, progress_cb)
    
    user_tasks[user_id]['running'] = False
    stats = joiner.stats
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ **任务完成**\n\n"
             f"成功: {stats['success']}\n"
             f"失败: {stats['failed']}\n"
             f"跳过: {stats['skipped']}\n"
             f"总计: {len(results)}",
        reply_markup=main_menu_kb(),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作"""
    await update.message.reply_text("❌ 已取消", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ==================== 主程序 ====================
def main():
    """启动 Bot"""
    init_db()
    logger.info("数据库初始化完成")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 对话处理器
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(button_handler),
        ],
        states={
            WAITING_SESSION_FILE: [MessageHandler(filters.Document.ALL, receive_session_file)],
            WAITING_STRING_SESSION: [MessageHandler(filters. TEXT & ~filters.COMMAND, receive_string_session)],
            WAITING_TDATA: [MessageHandler(filters.Document.ALL, receive_tdata)],
            WAITING_LINKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_links)],
            WAITING_TXT_FILE: [MessageHandler(filters.Document.ALL, receive_txt_file)],
            WAITING_INTERVAL: [MessageHandler(filters.TEXT & ~filters. COMMAND, receive_interval)],
            WAITING_LIMIT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_limit)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(button_handler),
        ],
        allow_reentry=True,
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(confirm_task, pattern='^(confirm|cancel)$'))
    
    logger.info("🤖 Bot 启动中...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
