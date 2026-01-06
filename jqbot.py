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

# ============== 配置 ==============
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0")) if os.getenv("API_ID") else 0
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")

# 文件上传限制
MAX_ZIP_FILE_SIZE = 100 * 1024 * 1024  # 100MB

DB_PATH = "jqbot.db"
SESSIONS_DIR = "sessions"
LOGS_DIR = "logs"

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

async def check_account_status(session_string: str) -> Tuple[bool, str]:
    """检查账户状态"""
    try:
        client = TelegramClient(
            StringSession(session_string),
            API_ID,
            API_HASH
        )
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

async def run_join_task(user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """运行加群任务"""
    task_running[user_id] = True
    task_paused[user_id] = False
    
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
                client = TelegramClient(
                    StringSession(account["session_string"]),
                    API_ID,
                    API_HASH
                )
                await client.connect()
                
                if not await client.is_user_authorized():
                    await update_account_status(account["id"], "unauthorized")
                    await client.disconnect()
                    continue
                
                # 加群
                success, message = await join_group(client, link)
                
                if success:
                    success_count += 1
                    await add_stat(user_id, account["id"], link, "success", message)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ 成功: {link}\n账户: {account['phone']}\n进度: {success_count}/{daily_limit}"
                    )
                else:
                    failed_count += 1
                    await add_stat(user_id, account["id"], link, "failed", message)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"❌ 失败: {link}\n原因: {message}"
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
            "请上传 session 文件或发送 session string\n\n"
            "支持格式：\n"
            "1. .session 文件\n"
            "2. session string (文本)\n"
            "3. .zip 压缩包（包含 session 文件）\n\n"
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
    """处理账户上传"""
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
                # 安全地解压 zip
                with tempfile.TemporaryDirectory() as extract_dir:
                    try:
                        with zipfile.ZipFile(temp_path, "r") as zip_ref:
                            # 验证 zip 内容安全性
                            for member in zip_ref.namelist():
                                # Check for path traversal
                                if member.startswith('/') or '..' in member:
                                    raise ValueError("Unsafe zip file path")
                                # Check file size (prevent zip bomb)
                                info = zip_ref.getinfo(member)
                                if info.file_size > MAX_ZIP_FILE_SIZE:
                                    raise ValueError("Zip file content too large")
                            
                            zip_ref.extractall(extract_dir)
                    except (zipfile.BadZipFile, ValueError) as e:
                        logger.warning(f"不安全的 zip 文件: {e}")
                        await update.message.reply_text(
                            "⚠️ ZIP 文件格式不正确或不安全",
                            reply_markup=get_accounts_menu_keyboard()
                        )
                        return ConversationHandler.END
                
                await update.message.reply_text(
                    "⚠️ ZIP 文件支持有限，请提供 session string",
                    reply_markup=get_accounts_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    "⚠️ 请直接发送 session string (文本格式)",
                    reply_markup=get_accounts_menu_keyboard()
                )
        finally:
            # 确保清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    elif update.message.text:
        # Handle session string
        session_string = update.message.text.strip()
        
        # Enhanced validation: Check session string format
        # Telethon session strings are typically base64 encoded and length > 200
        if len(session_string) > 200 and re.match(r'^[A-Za-z0-9+/=]+$', session_string):
            try:
                # 尝试连接验证
                is_valid, phone = await check_account_status(session_string)
                
                if is_valid:
                    await add_account(user_id, phone, session_string)
                    await update.message.reply_text(
                        f"✅ 账户添加成功\n手机号: {phone}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        f"❌ 账户验证失败: {phone}",
                        reply_markup=get_accounts_menu_keyboard()
                    )
            except Exception as e:
                logger.error(f"添加账户异常: {e}")
                await update.message.reply_text(
                    f"❌ 添加失败: 账户验证错误",
                    reply_markup=get_accounts_menu_keyboard()
                )
        else:
            await update.message.reply_text(
                "❌ Session string 格式不正确（应为 base64 编码，长度 > 200）",
                reply_markup=get_accounts_menu_keyboard()
            )
    
    return ConversationHandler.END

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
