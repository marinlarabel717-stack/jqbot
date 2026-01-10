#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Auto-Join Bot - 自动加群/加频道机器人
所有功能集成在一个文件中，使用 InlineKeyboard 按钮交互模式
"""

import os
import asyncio
import logging
import zipfile
import tempfile
import random
import re
import shutil
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path

# Telegram libraries
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from telethon import TelegramClient, functions, errors
from telethon.sessions import StringSession
import aiosqlite
import socks

# ============== 配置 ==============
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0")) if os.getenv("API_ID") else 0
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")

# 文件上传限制
MAX_ZIP_FILE_SIZE = 100 * 1024 * 1024  # 100MB

DB_PATH = "jqbot.db"
SESSIONS_DIR = "sessions"
LOGS_DIR = "logs"
PROXY_FILE = "proxy.txt"

# 创建必要的目录
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# 日志配置
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(f"{LOGS_DIR}/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 对话状态
(
    UPLOAD_ACCOUNT,
    ADD_LINK,
    UPLOAD_TXT,
    SET_INTERVAL,
    SET_LIMIT,
) = range(5)

# 任务状态
task_running = {}
task_paused = {}

# 代理管理
proxy_list = []
proxy_index = 0

# ============== 代理管理 ==============

def parse_proxy_line(line: str) -> Optional[Dict]:
    """解析单行代理，支持多种格式"""
    line = line.strip()
    
    # 跳过空行和注释
    if not line or line.startswith('#'):
        return None
    
    try:
        proxy_type = socks.SOCKS5  # 默认 SOCKS5
        host = None
        port = None
        username = None
        password = None
        
        # 1. 带协议前缀的格式: socks5://host:port 或 socks5://user:pass@host:port
        if '://' in line:
            protocol, rest = line.split('://', 1)
            protocol = protocol.lower()
            
            if protocol == 'socks5':
                proxy_type = socks.SOCKS5
            elif protocol == 'socks4':
                proxy_type = socks.SOCKS4
            elif protocol == 'http':
                proxy_type = socks.HTTP
            else:
                logger.warning(f"不支持的协议: {protocol}")
                return None
            
            # 检查是否有认证信息
            if '@' in rest:
                auth, addr = rest.rsplit('@', 1)
                if ':' in auth:
                    username, password = auth.split(':', 1)
                if ':' in addr:
                    host, port = addr.rsplit(':', 1)
            else:
                if ':' in rest:
                    host, port = rest.rsplit(':', 1)
        
        # 2. username:password@host:port 格式 (必须在 ABC 格式之前检查)
        elif '@' in line:
            auth, addr = line.rsplit('@', 1)
            if ':' in auth:
                username, password = auth.split(':', 1)
            if ':' in addr:
                host, port = addr.rsplit(':', 1)
        
        # 3. host:port:username:password 格式 (ABC代理格式)
        elif line.count(':') == 3:
            parts = line.split(':', 3)
            host, port, username, password = parts
        
        # 4. 基础格式: host:port
        elif ':' in line:
            host, port = line.rsplit(':', 1)
        
        else:
            logger.warning(f"无法解析代理格式: {line}")
            return None
        
        # 验证必需字段
        if not host or not port:
            logger.warning(f"代理缺少必需字段: {line}")
            return None
        
        # 转换端口为整数
        try:
            port = int(port)
        except ValueError:
            logger.warning(f"无效的端口号: {port}")
            return None
        
        return {
            'type': proxy_type,
            'host': host,
            'port': port,
            'username': username,
            'password': password,
            'raw': line
        }
    
    except Exception as e:
        logger.warning(f"解析代理失败: {line}, 错误: {e}")
        return None


def load_proxies() -> List[Dict]:
    """从 proxy.txt 加载代理列表"""
    global proxy_list
    proxy_list = []
    
    if not os.path.exists(PROXY_FILE):
        logger.warning(f"代理文件不存在: {PROXY_FILE}")
        return proxy_list
    
    try:
        with open(PROXY_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line in lines:
            proxy = parse_proxy_line(line)
            if proxy:
                proxy_list.append(proxy)
        
        logger.info(f"成功加载 {len(proxy_list)} 个代理")
    except Exception as e:
        logger.error(f"加载代理文件失败: {e}")
    
    return proxy_list


def get_proxy_for_telethon(proxy: Dict) -> Tuple:
    """转换为 Telethon 需要的 tuple 格式"""
    if proxy['username'] and proxy['password']:
        return (
            proxy['type'],
            proxy['host'],
            proxy['port'],
            True,  # rdns
            proxy['username'],
            proxy['password']
        )
    else:
        return (
            proxy['type'],
            proxy['host'],
            proxy['port']
        )


def get_next_proxy() -> Optional[Dict]:
    """获取下一个代理（轮换使用）"""
    global proxy_index
    
    if not proxy_list:
        return None
    
    proxy = proxy_list[proxy_index]
    proxy_index = (proxy_index + 1) % len(proxy_list)
    
    return proxy


def reload_proxies() -> int:
    """重新加载代理列表"""
    global proxy_index
    proxy_index = 0
    proxies = load_proxies()
    return len(proxies)


def mask_proxy(proxy: Dict) -> str:
    """脱敏显示代理信息"""
    host = proxy['host']
    port = proxy['port']
    
    if proxy['username']:
        # 隐藏部分密码
        username = proxy['username']
        password = proxy['password']
        if len(password) > 4:
            masked_pass = password[:2] + '*' * (len(password) - 4) + password[-2:]
        else:
            masked_pass = '***'
        return f"{host}:{port} (用户: {username}, 密码: {masked_pass})"
    else:
        return f"{host}:{port}"


async def test_proxy(proxy: Dict) -> Tuple[bool, str]:
    """测试单个代理连通性"""
    try:
        proxy_tuple = get_proxy_for_telethon(proxy)
        
        # 创建临时 client 测试连接
        client = TelegramClient(
            StringSession(),
            API_ID,
            API_HASH,
            proxy=proxy_tuple
        )
        
        # 尝试连接
        await client.connect()
        connected = client.is_connected()
        await client.disconnect()
        
        if connected:
            return True, f"代理连接成功: {mask_proxy(proxy)}"
        else:
            return False, f"代理连接失败: {mask_proxy(proxy)}"
    
    except Exception as e:
        logger.error(f"测试代理失败: {e}")
        return False, f"代理测试异常: {mask_proxy(proxy)} - {str(e)}"


# ============== 数据库 ==============

async def init_db():
    """初始化数据库"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 账户表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT,
                session_string TEXT,
                status TEXT DEFAULT 'offline',
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 链接表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                link TEXT NOT NULL,
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 统计表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER,
                link TEXT,
                status TEXT,
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 设置表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                interval_min INTEGER DEFAULT 30,
                interval_max INTEGER DEFAULT 60,
                daily_limit INTEGER DEFAULT 50
            )
        """)
        
        await db.commit()

async def add_account(user_id: int, phone: str, session_string: str) -> int:
    """添加账户"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (user_id, phone, session_string) VALUES (?, ?, ?)",
            (user_id, phone, session_string)
        )
        await db.commit()
        return cursor.lastrowid

async def get_accounts(user_id: int) -> List[Dict]:
    """获取用户的所有账户"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE user_id = ?", (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def delete_account(account_id: int):
    """删除账户"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()

async def update_account_status(account_id: int, status: str):
    """更新账户状态"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET status = ? WHERE id = ?", (status, account_id)
        )
        await db.commit()

async def add_link(user_id: int, link: str):
    """添加链接"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO links (user_id, link) VALUES (?, ?)", (user_id, link)
        )
        await db.commit()

async def get_links(user_id: int) -> List[Dict]:
    """获取用户的所有链接"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM links WHERE user_id = ?", (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def clear_links(user_id: int):
    """清空链接"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM links WHERE user_id = ?", (user_id,))
        await db.commit()

async def add_stat(user_id: int, account_id: int, link: str, status: str, message: str):
    """添加统计记录"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO stats (user_id, account_id, link, status, message) VALUES (?, ?, ?, ?, ?)",
            (user_id, account_id, link, status, message)
        )
        await db.commit()

async def get_stats(user_id: int, limit: int = 100) -> List[Dict]:
    """获取统计数据"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM stats WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_today_stats(user_id: int) -> Tuple[int, int]:
    """获取今日统计"""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM stats WHERE user_id = ? AND date(timestamp) = ? AND status = 'success'",
            (user_id, today)
        ) as cursor:
            success = (await cursor.fetchone())[0]
        
        async with db.execute(
            "SELECT COUNT(*) FROM stats WHERE user_id = ? AND date(timestamp) = ? AND status = 'failed'",
            (user_id, today)
        ) as cursor:
            failed = (await cursor.fetchone())[0]
        
        return success, failed

async def get_settings(user_id: int) -> Dict:
    """获取用户设置"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            else:
                # 返回默认设置
                return {
                    "interval_min": 30,
                    "interval_max": 60,
                    "daily_limit": 50
                }

async def update_settings(user_id: int, **kwargs):
    """更新设置"""
    # 允许的设置字段白名单及其对应的 SQL 查询
    allowed_queries = {
        "interval_min": "UPDATE settings SET interval_min = ? WHERE user_id = ?",
        "interval_max": "UPDATE settings SET interval_max = ? WHERE user_id = ?",
        "daily_limit": "UPDATE settings SET daily_limit = ? WHERE user_id = ?",
    }
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 先尝试插入
        await db.execute(
            "INSERT OR IGNORE INTO settings (user_id) VALUES (?)", (user_id,)
        )
        
        # 更新字段（使用预定义的查询）
        for key, value in kwargs.items():
            if key in allowed_queries:
                await db.execute(allowed_queries[key], (value, user_id))
        
        await db.commit()

# ============== 账户管理 ==============

def is_session_file_path(session_string: str) -> bool:
    """判断是否是 session 文件路径"""
    if not session_string:
        return False
    # 检查文件是否存在（带或不带 .session 后缀）
    if session_string.endswith('.session'):
        return os.path.exists(session_string)
    return os.path.exists(f"{session_string}.session")


def clean_phone_number(phone: str) -> str:
    """清理手机号，移除格式字符"""
    return phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')


def get_telegram_client(session_string: str, use_proxy: bool = True) -> TelegramClient:
    """根据 session 类型创建 TelegramClient"""
    proxy_tuple = None
    
    # 如果启用代理，获取下一个代理
    if use_proxy:
        proxy = get_next_proxy()
        if proxy:
            proxy_tuple = get_proxy_for_telethon(proxy)
            logger.info(f"使用代理: {mask_proxy(proxy)}")
    
    if is_session_file_path(session_string):
        # 文件路径
        session = session_string if not session_string.endswith('.session') else session_string.replace('.session', '')
        return TelegramClient(session, API_ID, API_HASH, proxy=proxy_tuple)
    else:
        # StringSession
        return TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=proxy_tuple)


async def check_account_status(session_string: str) -> Tuple[bool, str]:
    """检查账户状态 - 支持 StringSession 或文件路径"""
    try:
        client = get_telegram_client(session_string)
        await client.connect()
        
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return True, f"online - {me.phone}"
        else:
            await client.disconnect()
            return False, "未授权"
    except Exception as e:
        logger.error(f"检查账户状态失败: {e}")
        return False, str(e)

# ============== 加群核心 ==============

async def join_group(client: TelegramClient, link: str) -> Tuple[bool, str]:
    """加群核心逻辑"""
    try:
        # 解析链接
        if "t.me/" in link:
            username = link.split("t.me/")[1].split("?")[0].strip("/")
        else:
            username = link.strip()
        
        # 尝试加入
        if username.startswith("+"):
            # 私有群组邀请链接
            result = await client(functions.messages.ImportChatInviteRequest(
                hash=username[1:]
            ))
        else:
            # 公开群组
            result = await client(functions.channels.JoinChannelRequest(
                channel=username
            ))
        
        return True, "加群成功"
    
    except errors.FloodWaitError as e:
        return False, f"被限制，需等待 {e.seconds} 秒"
    except errors.UserAlreadyParticipantError:
        return False, "已经在群里"
    except errors.InviteHashExpiredError:
        return False, "邀请链接已过期"
    except errors.ChannelPrivateError:
        return False, "群组为私有"
    except Exception as e:
        logger.error(f"加群失败: {e}")
        return False, str(e)

async def auto_verify(client: TelegramClient) -> bool:
    """自动过验证（简单实现）"""
    try:
        # 这里可以扩展更复杂的验证逻辑
        # 例如：按钮点击、数学计算、关键词问答等
        await asyncio.sleep(2)
        return True
    except Exception as e:
        logger.error(f"自动验证失败: {e}")
        return False

async def test_proxy_connection(proxy: Dict) -> Tuple[bool, str]:
    """测试代理连通性"""
    try:
        proxy_tuple = get_proxy_for_telethon(proxy)
        
        # 使用代理创建临时 client 测试连接
        client = TelegramClient(
            StringSession(),
            API_ID,
            API_HASH,
            proxy=proxy_tuple
        )
        
        # 尝试连接
        await client.connect()
        connected = client.is_connected()
        await client.disconnect()
        
        if connected:
            return True, f"✅ 代理连接成功\n代理: {mask_proxy(proxy)}"
        else:
            return False, f"❌ 代理连接失败\n代理: {mask_proxy(proxy)}"
    
    except Exception as e:
        logger.error(f"测试代理连接失败: {e}")
        return False, f"❌ 代理连接异常\n代理: {mask_proxy(proxy)}\n错误: {str(e)}"

async def run_join_task(user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """运行加群任务"""
    task_running[user_id] = True
    task_paused[user_id] = False
    
    # 检查代理
    proxies = load_proxies()
    if not proxies:
        await update.callback_query.message.edit_text(
            "❌ 未找到可用代理\n\n"
            "请在脚本目录创建 proxy.txt 文件并添加代理\n"
            "支持格式：\n"
            "• host:port\n"
            "• host:port:user:pass\n"
            "• user:pass@host:port\n"
            "• socks5://host:port\n"
            "• ABC格式: xxx.abcproxy.vip:4950:user:pass"
        )
        task_running[user_id] = False
        return
    
    # 测试代理连通性
    proxy_ok, proxy_msg = await test_proxy_connection(proxies[0])
    if not proxy_ok:
        await update.callback_query.message.edit_text(
            f"❌ 代理连接失败\n\n{proxy_msg}\n\n请检查代理配置"
        )
        task_running[user_id] = False
        return
    
    # 获取设置
    settings = await get_settings(user_id)
    interval_min = settings["interval_min"]
    interval_max = settings["interval_max"]
    daily_limit = settings["daily_limit"]
    
    # 获取今日已加群数量
    success_count, failed_count = await get_today_stats(user_id)
    
    # 获取账户和链接
    accounts = await get_accounts(user_id)
    links = await get_links(user_id)
    
    if not accounts:
        await update.callback_query.message.edit_text("❌ 没有可用账户")
        task_running[user_id] = False
        return
    
    if not links:
        await update.callback_query.message.edit_text("❌ 没有可用链接")
        task_running[user_id] = False
        return
    
    # 开始加群
    for link_data in links:
        if not task_running.get(user_id):
            break
        
        # 检查暂停
        while task_paused.get(user_id):
            await asyncio.sleep(1)
        
        # 检查每日限制
        if success_count >= daily_limit:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ 已达到每日上限 {daily_limit}，任务结束"
            )
            break
        
        link = link_data["link"]
        
        # 轮换账户
        for account in accounts:
            if not task_running.get(user_id):
                break
            
            try:
                # 使用 helper 函数创建 client (会自动轮换代理)
                # 获取当前将使用的代理信息
                current_proxy = None
                if proxy_list:
                    current_proxy = proxy_list[(proxy_index - 1) % len(proxy_list)]
                
                client = get_telegram_client(account["session_string"])
                await client.connect()
                
                if not await client.is_user_authorized():
                    await update_account_status(account["id"], "unauthorized")
                    await client.disconnect()
                    continue
                
                # 加群
                success, message = await join_group(client, link)
                
                # 构建代理信息
                proxy_info = f"\n代理: {mask_proxy(current_proxy)}" if current_proxy else ""
                
                if success:
                    success_count += 1
                    await add_stat(user_id, account["id"], link, "success", message)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ 成功: {link}\n账户: {account['phone']}{proxy_info}\n进度: {success_count}/{daily_limit}"
                    )
                else:
                    failed_count += 1
                    await add_stat(user_id, account["id"], link, "failed", message)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"❌ 失败: {link}\n原因: {message}{proxy_info}"
                    )
                
                await client.disconnect()
                
                # 随机延迟
                delay = random.randint(interval_min, interval_max)
                await asyncio.sleep(delay)
                
                # 成功就跳到下一个链接
                if success:
                    break
                
            except Exception as e:
                logger.error(f"加群任务异常: {e}")
                await add_stat(user_id, account["id"], link, "error", str(e))
    
    task_running[user_id] = False
    await context.bot.send_message(
        chat_id=user_id,
        text=f"🏁 任务完成\n成功: {success_count}\n失败: {failed_count}"
    )

# ============== 按钮定义 ==============

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """主菜单"""
    keyboard = [
        [
            InlineKeyboardButton("📁 账户管理", callback_data="menu_accounts"),
            InlineKeyboardButton("🔗 链接管理", callback_data="menu_links"),
        ],
        [
            InlineKeyboardButton("⚙️ 加群设置", callback_data="menu_settings"),
            InlineKeyboardButton("🚀 开始任务", callback_data="start_task"),
        ],
        [
            InlineKeyboardButton("🌐 代理管理", callback_data="menu_proxy"),
        ],
        [
            InlineKeyboardButton("📊 统计面板", callback_data="show_stats"),
            InlineKeyboardButton("📋 日志查看", callback_data="show_logs"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_accounts_menu_keyboard() -> InlineKeyboardMarkup:
    """账户管理子菜单"""
    keyboard = [
        [
            InlineKeyboardButton("➕ 上传账户", callback_data="upload_account"),
            InlineKeyboardButton("📋 账户列表", callback_data="list_accounts"),
        ],
        [
            InlineKeyboardButton("🗑️ 删除账户", callback_data="delete_account"),
            InlineKeyboardButton("🔄 刷新状态", callback_data="refresh_status"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_links_menu_keyboard() -> InlineKeyboardMarkup:
    """链接管理子菜单"""
    keyboard = [
        [
            InlineKeyboardButton("➕ 添加链接", callback_data="add_link"),
            InlineKeyboardButton("📄 上传TXT", callback_data="upload_txt"),
        ],
        [
            InlineKeyboardButton("📋 链接列表", callback_data="list_links"),
            InlineKeyboardButton("🗑️ 清空链接", callback_data="clear_links"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu_keyboard() -> InlineKeyboardMarkup:
    """设置子菜单"""
    keyboard = [
        [
            InlineKeyboardButton("⏱️ 修改间隔", callback_data="set_interval"),
            InlineKeyboardButton("📊 修改上限", callback_data="set_limit"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_proxy_menu_keyboard() -> InlineKeyboardMarkup:
    """代理管理子菜单"""
    keyboard = [
        [
            InlineKeyboardButton("📋 代理列表", callback_data="list_proxies"),
            InlineKeyboardButton("🔄 重载代理", callback_data="reload_proxies"),
        ],
        [
            InlineKeyboardButton("🧪 测试代理", callback_data="test_proxy"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_task_control_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """任务控制"""
    is_running = task_running.get(user_id, False)
    is_paused = task_paused.get(user_id, False)
    
    keyboard = []
    
    if is_running:
        if is_paused:
            keyboard.append([
                InlineKeyboardButton("▶️ 继续", callback_data="resume_task"),
                InlineKeyboardButton("⏹️ 停止", callback_data="stop_task"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("⏸️ 暂停", callback_data="pause_task"),
                InlineKeyboardButton("⏹️ 停止", callback_data="stop_task"),
            ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu"),
    ])
    
    return InlineKeyboardMarkup(keyboard)

# ============== 回调处理 ==============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启动命令"""
    await update.message.reply_text(
        "🏠 主菜单\n\n欢迎使用 Telegram 自动加群机器人",
        reply_markup=get_main_menu_keyboard()
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # 主菜单
    if data == "main_menu":
        await query.edit_message_text(
            "🏠 主菜单\n\n欢迎使用 Telegram 自动加群机器人",
            reply_markup=get_main_menu_keyboard()
        )
    
    # 账户管理
    elif data == "menu_accounts":
        await query.edit_message_text(
            "📁 账户管理",
            reply_markup=get_accounts_menu_keyboard()
        )
    
    elif data == "upload_account":
        await query.edit_message_text(
            "请选择登录方式或上传账户文件\n\n"
            "支持格式：\n"
            "1. 📱 手动验证码登录 - 发送手机号码\n"
            "2. 📄 session 文件 (.session)\n"
            "3. 📋 session+json 文件 (.zip包含两个文件)\n"
            "4. 📦 ZIP 文件 (包含 session/tdata)\n"
            "5. 🗂️ tdata 格式 (zip: 手机号/tdata/xxx/key_datas)\n\n"
            "发送 /cancel 取消"
        )
        return UPLOAD_ACCOUNT
    
    elif data == "list_accounts":
        accounts = await get_accounts(user_id)
        if not accounts:
            text = "📋 账户列表\n\n暂无账户"
        else:
            text = "📋 账户列表\n\n"
            for acc in accounts:
                status_icon = "🟢" if acc["status"] == "online" else "🔴"
                text += f"{status_icon} ID: {acc['id']}\n"
                text += f"   手机: {acc['phone'] or '未知'}\n"
                text += f"   状态: {acc['status']}\n\n"
        
        await query.edit_message_text(
            text,
            reply_markup=get_accounts_menu_keyboard()
        )
    
    elif data == "delete_account":
        accounts = await get_accounts(user_id)
        if not accounts:
            await query.edit_message_text(
                "暂无账户可删除",
                reply_markup=get_accounts_menu_keyboard()
            )
        else:
            keyboard = []
            for acc in accounts:
                keyboard.append([
                    InlineKeyboardButton(
                        f"删除 {acc['phone'] or acc['id']}",
                        callback_data=f"del_acc_{acc['id']}"
                    )
                ])
            keyboard.append([
                InlineKeyboardButton("🔙 返回", callback_data="menu_accounts")
            ])
            
            await query.edit_message_text(
                "选择要删除的账户：",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    elif data.startswith("del_acc_"):
        account_id = int(data.split("_")[2])
        await delete_account(account_id)
        await query.edit_message_text(
            "✅ 账户已删除",
            reply_markup=get_accounts_menu_keyboard()
        )
    
    elif data == "refresh_status":
        accounts = await get_accounts(user_id)
        if not accounts:
            await query.edit_message_text(
                "暂无账户",
                reply_markup=get_accounts_menu_keyboard()
            )
        else:
            await query.edit_message_text("🔄 正在刷新状态...")
            
            for acc in accounts:
                is_online, status = await check_account_status(acc["session_string"])
                await update_account_status(
                    acc["id"],
                    "online" if is_online else "offline"
                )
            
            await query.edit_message_text(
                "✅ 状态已刷新",
                reply_markup=get_accounts_menu_keyboard()
            )
    
    # 链接管理
    elif data == "menu_links":
        await query.edit_message_text(
            "🔗 链接管理",
            reply_markup=get_links_menu_keyboard()
        )
    
    elif data == "add_link":
        await query.edit_message_text(
            "请发送群组/频道链接\n\n"
            "支持格式：\n"
            "1. https://t.me/groupname\n"
            "2. @groupname\n"
            "3. https://t.me/+invitehash\n\n"
            "发送 /cancel 取消"
        )
        return ADD_LINK
    
    elif data == "upload_txt":
        await query.edit_message_text(
            "请上传包含链接的 TXT 文件\n\n"
            "格式：每行一个链接\n\n"
            "发送 /cancel 取消"
        )
        return UPLOAD_TXT
    
    elif data == "list_links":
        links = await get_links(user_id)
        if not links:
            text = "📋 链接列表\n\n暂无链接"
        else:
            text = f"📋 链接列表 (共 {len(links)} 个)\n\n"
            for idx, link in enumerate(links[:20], 1):
                text += f"{idx}. {link['link']}\n"
            
            if len(links) > 20:
                text += f"\n... 还有 {len(links) - 20} 个链接"
        
        await query.edit_message_text(
            text,
            reply_markup=get_links_menu_keyboard()
        )
    
    elif data == "clear_links":
        keyboard = [
            [
                InlineKeyboardButton("✅ 确认清空", callback_data="confirm_clear_links"),
                InlineKeyboardButton("❌ 取消", callback_data="menu_links"),
            ]
        ]
        await query.edit_message_text(
            "⚠️ 确定要清空所有链接吗？",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "confirm_clear_links":
        await clear_links(user_id)
        await query.edit_message_text(
            "✅ 已清空所有链接",
            reply_markup=get_links_menu_keyboard()
        )
    
    # 设置
    elif data == "menu_settings":
        settings = await get_settings(user_id)
        text = (
            f"⚙️ 加群设置\n\n"
            f"当前间隔: {settings['interval_min']}-{settings['interval_max']}秒\n"
            f"每日上限: {settings['daily_limit']}个"
        )
        await query.edit_message_text(
            text,
            reply_markup=get_settings_menu_keyboard()
        )
    
    elif data == "set_interval":
        await query.edit_message_text(
            "请发送时间间隔范围（秒）\n\n"
            "格式: 最小值-最大值\n"
            "例如: 30-60\n\n"
            "发送 /cancel 取消"
        )
        return SET_INTERVAL
    
    elif data == "set_limit":
        await query.edit_message_text(
            "请发送每日加群上限\n\n"
            "例如: 50\n\n"
            "发送 /cancel 取消"
        )
        return SET_LIMIT
    
    # 代理管理
    elif data == "menu_proxy":
        proxies = load_proxies()
        text = (
            f"🌐 代理管理\n\n"
            f"已加载代理: {len(proxies)} 个"
        )
        await query.edit_message_text(
            text,
            reply_markup=get_proxy_menu_keyboard()
        )
    
    elif data == "list_proxies":
        proxies = load_proxies()
        if not proxies:
            text = "📋 代理列表\n\n暂无代理\n\n请在脚本目录创建 proxy.txt 文件"
        else:
            text = f"📋 代理列表 (共 {len(proxies)} 个)\n\n"
            for idx, proxy in enumerate(proxies[:10], 1):
                text += f"{idx}. {mask_proxy(proxy)}\n"
            
            if len(proxies) > 10:
                text += f"\n... 还有 {len(proxies) - 10} 个代理"
        
        await query.edit_message_text(
            text,
            reply_markup=get_proxy_menu_keyboard()
        )
    
    elif data == "reload_proxies":
        count = reload_proxies()
        await query.edit_message_text(
            f"🔄 已重新加载 {count} 个代理",
            reply_markup=get_proxy_menu_keyboard()
        )
    
    elif data == "test_proxy":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text(
                "❌ 暂无代理可测试\n\n请先添加代理到 proxy.txt",
                reply_markup=get_proxy_menu_keyboard()
            )
        else:
            await query.edit_message_text("🧪 正在测试第一个代理...")
            
            success, message = await test_proxy(proxies[0])
            
            status_icon = "✅" if success else "❌"
            await query.edit_message_text(
                f"{status_icon} 测试结果\n\n{message}",
                reply_markup=get_proxy_menu_keyboard()
            )
    
    # 任务控制
    elif data == "start_task":
        if task_running.get(user_id):
            success_count, failed_count = await get_today_stats(user_id)
            settings = await get_settings(user_id)
            status = "暂停中" if task_paused.get(user_id) else "运行中"
            
            text = (
                f"🚀 任务控制\n\n"
                f"状态: {status}\n"
                f"进度: {success_count}/{settings['daily_limit']}\n"
                f"失败: {failed_count}"
            )
            await query.edit_message_text(
                text,
                reply_markup=get_task_control_keyboard(user_id)
            )
        else:
            await query.edit_message_text("⏳ 正在启动任务...")
            
            # 在后台运行任务
            asyncio.create_task(run_join_task(user_id, update, context))
            
            await asyncio.sleep(1)
            
            success_count, failed_count = await get_today_stats(user_id)
            settings = await get_settings(user_id)
            
            text = (
                f"🚀 任务控制\n\n"
                f"状态: 运行中\n"
                f"进度: {success_count}/{settings['daily_limit']}\n"
                f"失败: {failed_count}"
            )
            await query.edit_message_text(
                text,
                reply_markup=get_task_control_keyboard(user_id)
            )
    
    elif data == "pause_task":
        task_paused[user_id] = True
        await query.edit_message_text(
            "⏸️ 任务已暂停",
            reply_markup=get_task_control_keyboard(user_id)
        )
    
    elif data == "resume_task":
        task_paused[user_id] = False
        await query.edit_message_text(
            "▶️ 任务已继续",
            reply_markup=get_task_control_keyboard(user_id)
        )
    
    elif data == "stop_task":
        task_running[user_id] = False
        task_paused[user_id] = False
        await query.edit_message_text(
            "⏹️ 任务已停止",
            reply_markup=get_main_menu_keyboard()
        )
    
    # 统计
    elif data == "show_stats":
        success_count, failed_count = await get_today_stats(user_id)
        total = success_count + failed_count
        success_rate = (success_count / total * 100) if total > 0 else 0
        
        text = (
            f"📊 统计面板\n\n"
            f"今日成功: {success_count}\n"
            f"今日失败: {failed_count}\n"
            f"成功率: {success_rate:.1f}%\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # 日志
    elif data == "show_logs":
        stats = await get_stats(user_id, limit=10)
        
        if not stats:
            text = "📋 日志查看\n\n暂无日志"
        else:
            text = "📋 最近10条日志\n\n"
            for stat in stats:
                status_icon = "✅" if stat["status"] == "success" else "❌"
                timestamp = stat["timestamp"].split(".")[0]
                text += f"{status_icon} {timestamp}\n"
                text += f"   链接: {stat['link']}\n"
                text += f"   {stat['message']}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return ConversationHandler.END

# ============== 消息处理 ==============

async def handle_upload_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理账户上传 - 支持多种格式"""
    user_id = update.effective_user.id
    
    if update.message.document:
        # 处理文件上传
        file = await update.message.document.get_file()
        file_name = update.message.document.file_name
        
        # 使用安全的临时文件
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            temp_path = tmp_file.name
        
        try:
            await file.download_to_drive(temp_path)
            
            if file_name.endswith(".zip"):
                # 处理 ZIP 文件
                success, message, phone = await process_zip_account(temp_path, user_id)
                if success:
                    await update.message.reply_text(
                        f"✅ 账户添加成功\n{message}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        f"❌ {message}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
            
            elif file_name.endswith(".session"):
                # 处理单个 session 文件
                success, message, phone = await process_session_file(temp_path, user_id)
                if success:
                    await update.message.reply_text(
                        f"✅ 账户添加成功\n手机号: {phone}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        f"❌ {message}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
            
            else:
                await update.message.reply_text(
                    "⚠️ 不支持的文件格式\n请上传 .session 或 .zip 文件",
                    reply_markup=get_accounts_menu_keyboard()
                )
        
        except Exception as e:
            logger.error(f"处理文件失败: {e}")
            await update.message.reply_text(
                "❌ 文件处理失败",
                reply_markup=get_accounts_menu_keyboard()
            )
        finally:
            # 确保清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    elif update.message.text:
        # 处理手机号码 - 手动验证码登录
        phone = update.message.text.strip()
        
        # 验证手机号格式
        phone_pattern = r'^\+?[0-9\s\-\(\)]+$'
        cleaned_phone = clean_phone_number(phone)
        
        if re.match(phone_pattern, phone) and len(cleaned_phone) >= 10:
            try:
                # 初始化手动登录流程
                await update.message.reply_text(
                    f"📱 正在发起登录请求...\n手机号: {phone}\n\n"
                    "⚠️ 由于安全限制，手动登录功能暂不可用\n"
                    "请使用以下方式：\n"
                    "1. 上传 .session 文件\n"
                    "2. 上传包含 session 的 ZIP 文件\n"
                    "3. 上传 tdata 格式的 ZIP 文件",
                    reply_markup=get_accounts_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"手动登录失败: {e}")
                await update.message.reply_text(
                    "❌ 登录失败",
                    reply_markup=get_accounts_menu_keyboard()
                )
        else:
            await update.message.reply_text(
                "❌ 手机号格式不正确\n格式: +8613800138000\n\n或上传账户文件",
                reply_markup=get_accounts_menu_keyboard()
            )
    
    return ConversationHandler.END


async def process_session_file(file_path: str, user_id: int) -> Tuple[bool, str, str]:
    """处理单个 session 文件"""
    dest_path = None
    try:
        # 使用 Telethon 加载 session 文件
        session_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # 将文件复制到 sessions 目录
        dest_path = os.path.join(SESSIONS_DIR, f"user_{user_id}_{session_name}.session")
        shutil.copy(file_path, dest_path)
        
        # 尝试连接验证
        session_file = dest_path.replace('.session', '')
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        
        if await client.is_user_authorized():
            me = await client.get_me()
            phone = me.phone if me.phone else "未知"
            
            # 保存 session 文件路径到数据库 (使用文件路径作为标识)
            # 注意: 这里简化处理，直接使用相对路径
            session_string = session_file
            
            await client.disconnect()
            
            # 保存到数据库
            await add_account(user_id, phone, session_string)
            
            return True, f"手机号: {phone}", phone
        else:
            await client.disconnect()
            # 删除无效的 session 文件
            if dest_path and os.path.exists(dest_path):
                os.remove(dest_path)
            return False, "Session 文件未授权或已过期", ""
    
    except Exception as e:
        logger.error(f"处理 session 文件失败: {e}")
        # 清理失败的文件
        if dest_path and os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except (OSError, FileNotFoundError) as cleanup_error:
                logger.warning(f"清理文件失败: {cleanup_error}")
        return False, "Session 文件处理失败", ""


async def process_zip_account(zip_path: str, user_id: int) -> Tuple[bool, str, str]:
    """处理 ZIP 文件 - 支持 session、tdata 格式"""
    with tempfile.TemporaryDirectory() as extract_dir:
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # 验证 zip 内容安全性
                for member in zip_ref.namelist():
                    # Check for path traversal
                    if member.startswith('/') or '..' in member:
                        return False, "ZIP 文件包含不安全的路径", ""
                    # Check file size (prevent zip bomb)
                    info = zip_ref.getinfo(member)
                    if info.file_size > MAX_ZIP_FILE_SIZE:
                        return False, "ZIP 文件内容过大", ""
                
                zip_ref.extractall(extract_dir)
        except (zipfile.BadZipFile, ValueError) as e:
            logger.warning(f"无效的 zip 文件: {e}")
            return False, "ZIP 文件格式不正确", ""
        
        # 检查是否是 tdata 格式
        tdata_result = await process_tdata_format(extract_dir, user_id)
        if tdata_result[0]:
            return tdata_result
        
        # 检查是否有 session 文件
        session_files = []
        json_files = []
        
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.session'):
                    session_files.append(os.path.join(root, file))
                elif file.endswith('.json'):
                    json_files.append(os.path.join(root, file))
        
        if session_files:
            # 处理第一个找到的 session 文件
            result = await process_session_file(session_files[0], user_id)
            if result[0]:
                return result
            return False, "Session 文件无效", ""
        
        return False, "ZIP 文件中未找到有效的 session 或 tdata 文件", ""


async def process_tdata_format(extract_dir: str, user_id: int) -> Tuple[bool, str, str]:
    """处理 tdata 格式: phone_number/tdata/D877F783D5D3EF8C/key_datas"""
    try:
        # 遍历查找 tdata 结构
        for item in os.listdir(extract_dir):
            item_path = os.path.join(extract_dir, item)
            if not os.path.isdir(item_path):
                continue
            
            # 检查是否是手机号格式
            phone_candidate = item
            cleaned = clean_phone_number(phone_candidate)
            if not cleaned.isdigit():
                continue
            
            # 查找 tdata 目录
            tdata_path = os.path.join(item_path, "tdata")
            if not os.path.exists(tdata_path):
                continue
            
            # 查找类似 D877F783D5D3EF8C 的子目录和 key_datas 文件
            found_valid = False
            for subdir in os.listdir(tdata_path):
                subdir_path = os.path.join(tdata_path, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                
                key_datas_path = os.path.join(subdir_path, "key_datas")
                if os.path.exists(key_datas_path):
                    found_valid = True
                    break
            
            if found_valid:
                # 找到有效的 tdata 格式
                # 注意：tdata 格式需要使用 Telegram Desktop 的 API 或专门的转换工具
                logger.info(f"发现 tdata 格式，手机号: {phone_candidate}")
                return False, f"检测到 tdata 格式 (手机号: {phone_candidate})\n该格式需要特殊转换工具\n建议使用 session 文件替代", phone_candidate
        
        return False, "", ""
    
    except Exception as e:
        logger.error(f"处理 tdata 格式失败: {e}")
        return False, "", ""

async def handle_add_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理添加链接"""
    user_id = update.effective_user.id
    link = update.message.text.strip()
    
    # 简单验证
    if "t.me/" in link or link.startswith("@") or link.startswith("+"):
        await add_link(user_id, link)
        await update.message.reply_text(
            f"✅ 链接已添加\n{link}",
            reply_markup=get_links_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ 链接格式不正确",
            reply_markup=get_links_menu_keyboard()
        )
    
    return ConversationHandler.END

async def handle_upload_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 TXT 文件上传"""
    user_id = update.effective_user.id
    
    if update.message.document:
        file = await update.message.document.get_file()
        
        # 使用安全的临时文件
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.txt') as tmp_file:
            temp_path = tmp_file.name
        
        try:
            await file.download_to_drive(temp_path)
            
            with open(temp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            count = 0
            for line in lines:
                link = line.strip()
                if link and ("t.me/" in link or link.startswith("@") or link.startswith("+")):
                    await add_link(user_id, link)
                    count += 1
            
            await update.message.reply_text(
                f"✅ 成功添加 {count} 个链接",
                reply_markup=get_links_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"读取文件失败: {e}")
            await update.message.reply_text(
                f"❌ 读取文件失败: 文件格式错误",
                reply_markup=get_links_menu_keyboard()
            )
        finally:
            # 确保清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
    else:
        await update.message.reply_text(
            "❌ 请上传 TXT 文件",
            reply_markup=get_links_menu_keyboard()
        )
    
    return ConversationHandler.END

async def handle_set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置间隔"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 解析格式: 30-60
    match = re.match(r"(\d+)-(\d+)", text)
    if match:
        min_val = int(match.group(1))
        max_val = int(match.group(2))
        
        if min_val < max_val and min_val >= 10:
            await update_settings(user_id, interval_min=min_val, interval_max=max_val)
            await update.message.reply_text(
                f"✅ 间隔已设置为 {min_val}-{max_val} 秒",
                reply_markup=get_settings_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ 格式错误，最小值应大于10且小于最大值",
                reply_markup=get_settings_menu_keyboard()
            )
    else:
        await update.message.reply_text(
            "❌ 格式错误，请使用: 最小值-最大值",
            reply_markup=get_settings_menu_keyboard()
        )
    
    return ConversationHandler.END

async def handle_set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置上限"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    try:
        limit = int(text)
        if limit > 0:
            await update_settings(user_id, daily_limit=limit)
            await update.message.reply_text(
                f"✅ 每日上限已设置为 {limit}",
                reply_markup=get_settings_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ 上限必须大于0",
                reply_markup=get_settings_menu_keyboard()
            )
    except ValueError:
        await update.message.reply_text(
            "❌ 请输入有效的数字",
            reply_markup=get_settings_menu_keyboard()
        )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作"""
    await update.message.reply_text(
        "❌ 操作已取消",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# ============== 主函数 ==============

async def post_init(application: Application):
    """启动后初始化"""
    await init_db()
    logger.info("数据库初始化完成")

def main():
    """主函数"""
    # 创建应用
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 添加 /start 命令处理器
    application.add_handler(CommandHandler("start", start_command))
    
    # 添加会话处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback)],
        states={
            UPLOAD_ACCOUNT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_upload_account)
            ],
            ADD_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_link)
            ],
            UPLOAD_TXT: [
                MessageHandler(filters.Document.ALL, handle_upload_txt)
            ],
            SET_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_interval)
            ],
            SET_LIMIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_limit)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    
    application.add_handler(conv_handler)
    
    # 启动机器人
    logger.info("机器人启动中...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
