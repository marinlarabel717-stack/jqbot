# Changes - Join Group System Refactoring (Professional Version)

## Overview
Complete professional refactoring of the Telegram auto-join bot with enhanced account management, intelligent link tracking, and smart sleep/wake cycles.

## Version
- **Date**: 2026-01-10
- **Type**: Major Feature Enhancement
- **Backward Compatible**: Yes (automatic migration)

## What's New

### 🎯 Core Features

#### 1. Smart Account Management
- **Sleep Cycles**: Accounts automatically sleep after N joins (configurable)
- **Daily Limits**: Per-account daily limits prevent overuse
- **Auto-Detection**: Frozen/banned accounts automatically detected and removed
- **Status Tracking**: Track joins per account (today/total) and last join time

#### 2. Intelligent Link Management
- **Auto-Deduplication**: Duplicate links automatically skipped
- **Status Tracking**: Each link tracks status (pending/success/failed/invalid)
- **Smart Filtering**: Invalid links auto-skipped in future runs
- **Join History**: Track which account successfully joined each link

#### 3. Enhanced Configuration System
- **Join Interval**: Configure min-max delay between joins (default: 120-180s)
- **Sleep Settings**: Configure sleep after N joins for M minutes (default: 10/30)
- **Per-Account Limit**: Max joins per account per day (default: 20)
- **Daily Total Limit**: Max total joins across all accounts (default: 50)
- **Repeat Joins**: Toggle whether to allow rejoining same groups
- **Anti-Flood Delay**: Extra random delay to avoid detection (default: 0-30s)

#### 4. Professional Join Logic
- **Smart Rotation**: Automatically switches to next available account
- **Sleep Management**: Waits for sleeping accounts to wake up
- **Error Recovery**: Comprehensive error handling with appropriate actions
- **Progress Tracking**: Detailed real-time progress with statistics

### 📊 Database Changes

#### Accounts Table - New Fields
```sql
today_joined INTEGER DEFAULT 0      -- Today's join count
total_joined INTEGER DEFAULT 0      -- Lifetime join count
last_join_time DATETIME            -- Last successful join timestamp
sleep_until DATETIME               -- Sleep until this time
```

#### Links Table - New Fields
```sql
status TEXT DEFAULT 'pending'      -- pending/success/failed/invalid
fail_reason TEXT                   -- Error message if failed
joined_by INTEGER                  -- Account ID that joined
```

#### Settings Table - New Fields
```sql
allow_repeat INTEGER DEFAULT 0         -- Allow repeat joins (0/1)
sleep_after_count INTEGER DEFAULT 10   -- Sleep after N joins
sleep_duration INTEGER DEFAULT 30      -- Sleep duration (minutes)
max_per_account INTEGER DEFAULT 20     -- Per-account daily limit
anti_flood_extra INTEGER DEFAULT 30    -- Extra delay (seconds)
```

### 🎨 UI Improvements

#### New Settings Menu
```
⏱️ 加群间隔      😴 休眠设置
🔢 单号上限      📊 每日总上限
🔄 重复加群      🛡️ 防风控延迟
📋 查看当前配置
🔙 返回主菜单
```

#### Settings Display
Shows all 6 configuration parameters:
- Join interval range
- Sleep rules (count/duration)
- Per-account daily limit
- Total daily limit
- Repeat joins status
- Anti-flood delay range

### 🔧 New Functions

#### Database Functions (9 new)
- `get_pending_links()` - Get pending links only
- `update_link_status()` - Update link status and reason
- `check_already_joined()` - Check for duplicate joins
- `increment_account_join_count()` - Update account counters
- `get_account_today_count()` - Get today's count for account
- `set_account_sleep()` - Put account to sleep
- `get_available_account()` - Get next usable account
- `get_next_wake_time()` - Get earliest wake time
- `reset_daily_counters()` - Reset all daily counters

#### UI Functions (4 new)
- `handle_set_sleep()` - Configure sleep settings
- `handle_set_max_per_account()` - Set per-account limit
- `handle_set_anti_flood()` - Set anti-flood delay
- Inline toggle for repeat joins

### 🚀 Enhanced Behavior

#### Join Task Flow
1. Load all settings (8 parameters)
2. Check proxy availability
3. Get accounts and pending links
4. Show startup summary
5. For each link:
   - Check daily limit
   - Get available account (not sleeping, under limit)
   - If all sleeping, wait for next wake
   - Check for duplicate (if repeat disabled)
   - Attempt join with error handling
   - Update link status and account stats
   - Check if account needs sleep
   - Apply delays (base + anti-flood)
6. Show completion statistics

#### Error Handling Improvements
- **FloodWaitError**: Automatically waits the required time
- **UserAlreadyParticipant**: Counts as success
- **Invalid Links**: Marked as invalid, skipped in future
- **Frozen Accounts**: Automatically deleted with notification
- **Banned Accounts**: Automatically deleted with notification

#### Progress Messages
```
🚀 任务启动
账号: 10 个
待加群: 847 个
配置: 间隔120-180s | 休眠10个/30分钟 | 单号上限20

✅ 成功: https://t.me/group1
账号: +5585987930687
进度: 1/50

⏳ 等待 156 秒后继续...

😴 账号 +5585987930687 已加 10 个群，休眠 30 分钟

❄️ 账号 +5511999887766 已冻结，自动删除

🏁 任务完成
✅ 成功: 47
❌ 失败: 3
🗑️ 无效链接: 5
❄️ 冻结账号: 1
```

## Migration Guide

### For Existing Users
**No action required!** The bot will automatically:
1. Add new database columns on first run
2. Use default values for new settings
3. Preserve all existing data
4. Continue working normally

### For New Users
Just follow the standard installation:
```bash
pip install -r requirements.txt
python jqbot.py
```

## Technical Details

### Code Changes
- **File**: `jqbot.py`
- **Lines Added**: +565
- **Lines Removed**: -113
- **Net Change**: +452 lines
- **Functions Added**: 13 new functions
- **Callbacks Added**: 5 new callback handlers
- **States Added**: 3 new conversation states

### Testing Coverage
- ✅ Database schema migration
- ✅ Link deduplication logic
- ✅ Account join counting
- ✅ Python syntax validation
- ✅ Module structure validation
- ✅ All callback handlers registered
- ✅ Conversation states properly defined

### Performance
- No performance degradation
- Efficient SQL queries with indexes
- Async operations throughout
- Minimal memory footprint

### Security
- ✅ SQL injection protected (parameterized queries)
- ✅ Input validation on all user inputs
- ✅ Safe error handling (no stack traces)
- ✅ Session files properly managed
- ✅ No sensitive data logged

## Breaking Changes
**None!** All changes are backward compatible.

## Known Limitations
1. Daily counter reset requires manual trigger or cron job
2. Sleep cycles reset on bot restart
3. Link status doesn't update retroactively for old links

## Future Enhancements
- Automatic daily counter reset (scheduler)
- Multi-language support
- Advanced proxy rotation strategies
- Web dashboard

## Support
For issues or questions:
- GitHub Issues: https://github.com/marinlarabel717-stack/jqbot/issues
- Check README.md for documentation

## Credits
- Original Developer: marinlarabel717-stack
- Refactoring: Complete professional rewrite
- Testing: Comprehensive validation

---
**Version**: Professional Edition v2.0
**Status**: ✅ Production Ready
**Last Updated**: 2026-01-10
