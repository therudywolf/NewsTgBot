"""Database module for storing channels, news, and sessions.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License.
See LICENSE file for details.
"""
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import config

logger = logging.getLogger(__name__)


class Database:
    """Database manager for news bot."""
    
    def __init__(self, db_path: str = None):
        """Initialize database connection."""
        self.db_path = db_path or config.DATABASE_PATH
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def _init_database(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        
        # Create channels table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                title TEXT,
                added_date TEXT NOT NULL
            )
        """)
        
        # Create news table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                date TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                tags_generated INTEGER DEFAULT 0,
                UNIQUE(channel_id, message_id)
            )
        """)
        
        # Create tags table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Create news_tags table (many-to-many relationship)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                FOREIGN KEY (news_id) REFERENCES news (id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                UNIQUE(news_id, tag_id)
            )
        """)
        
        # Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                aggregated_text TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for better performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_channel_date 
            ON news(channel_id, date)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_date 
            ON news(date)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_name 
            ON tags(name)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_tags_news 
            ON news_tags(news_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_tags_tag 
            ON news_tags(tag_id)
        """)
        
        # Migration: add tags_generated column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN tags_generated INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Migration: add source_type column to channels table if it doesn't exist
        try:
            cursor.execute("ALTER TABLE channels ADD COLUMN source_type TEXT DEFAULT 'telegram_bot'")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Create sources table for additional source configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_config TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE,
                UNIQUE(channel_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Posting bots — multiple Telegram bot tokens or the user account that
        # can publish aggregated news. `kind` is 'bot_api' or 'telethon'.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posting_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'bot_api',
                token TEXT,
                default_chat_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # LLM prompt templates per task. `task` is one of:
        # 'dedup', 'summary', 'tags', 'repost'. There can be many named
        # variants per task; the active one is used by the worker.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                name TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                user_template TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task, name)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_prompts_task
            ON llm_prompts(task, is_active DESC)
        """)

        # Pipelines — named workflows composed of ordered steps. Each pipeline
        # may have a cron schedule (used by stage C scheduler) and lives in
        # an optional `group_name` for visual grouping in the UI.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipelines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_name TEXT NOT NULL DEFAULT 'default',
                enabled INTEGER NOT NULL DEFAULT 1,
                schedule_cron TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                type TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (pipeline_id) REFERENCES pipelines(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pipeline_steps_pipeline
            ON pipeline_steps(pipeline_id, position)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT 'manual',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                output TEXT,
                FOREIGN KEY (pipeline_id) REFERENCES pipelines(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline
            ON pipeline_runs(pipeline_id, started_at DESC)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_step_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_id INTEGER,
                position INTEGER NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                input TEXT,
                output TEXT,
                error TEXT,
                FOREIGN KEY (run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pipeline_step_runs_run
            ON pipeline_step_runs(run_id, position)
        """)

        # User-defined groups of sources for bulk parsing.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL DEFAULT '#5dd2a2',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_group_members (
                group_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (group_id, channel_id),
                FOREIGN KEY (group_id) REFERENCES source_groups(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_group_members_channel
            ON source_group_members(channel_id)
        """)

        # Multiple posting destinations per bot.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posting_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES posting_bots(id) ON DELETE CASCADE,
                UNIQUE(bot_id, chat_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_posting_targets_bot
            ON posting_targets(bot_id)
        """)

        # Bot identity cache populated by Bot API getMe.
        try:
            cursor.execute("ALTER TABLE posting_bots ADD COLUMN bot_username TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE posting_bots ADD COLUMN bot_first_name TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE posting_bots ADD COLUMN bot_id_telegram INTEGER")
        except sqlite3.OperationalError:
            pass

        # Audit log of admin actions (used by Sprint 3, table created here so
        # later sprints don't need a migration).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                payload TEXT,
                ip TEXT,
                at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_at
            ON audit_log(at DESC)
        """)

        # Media attachments captured from parsed news items (stage D).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'image',
                url TEXT,
                local_path TEXT,
                mime TEXT,
                width INTEGER,
                height INTEGER,
                downloaded INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_media_news
            ON news_media(news_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sources_channel 
            ON sources(channel_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sources_type 
            ON sources(source_type)
        """)
        
        conn.commit()
        conn.close()
    
    def add_channel(
        self, 
        channel_id: int, 
        username: str = None, 
        title: str = None,
        source_type: str = 'telegram_bot'
    ) -> bool:
        """
        Add a channel to the database.
        
        Args:
            channel_id: Channel ID
            username: Channel username
            title: Channel title
            source_type: Source type (default: 'telegram_bot')
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO channels (channel_id, username, title, added_date, source_type)
                VALUES (?, ?, ?, ?, ?)
            """, (channel_id, username, title, datetime.now().isoformat(), source_type))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error adding channel: {e}")
            return False
        finally:
            conn.close()
    
    def remove_channel(self, channel_id: int) -> bool:
        """Remove a channel from the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            removed = cursor.rowcount > 0
            cursor.execute("DELETE FROM sources WHERE channel_id = ?", (channel_id,))
            # Also delete associated news
            cursor.execute("DELETE FROM news WHERE channel_id = ?", (channel_id,))
            conn.commit()
            return removed
        except sqlite3.Error as e:
            logger.error(f"Error removing channel: {e}")
            return False
        finally:
            conn.close()
    
    def get_all_channels(self) -> List[Dict[str, Any]]:
        """Get all channels from the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT channel_id, username, title, added_date, 
                   COALESCE(source_type, 'telegram_bot') as source_type 
            FROM channels
        """)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_channel_by_id(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get channel by channel_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT channel_id, username, title, added_date,
                   COALESCE(source_type, 'telegram_bot') as source_type
            FROM channels WHERE channel_id = ?
        """, (channel_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def add_news(self, channel_id: int, message_id: int, text: str, date: str) -> Optional[int]:
        """Add news item to the database. Returns news_id if inserted, None otherwise."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO news (channel_id, message_id, text, date)
                VALUES (?, ?, ?, ?)
            """, (channel_id, message_id, text, date))
            conn.commit()
            
            if cursor.rowcount > 0:
                # Get the inserted news ID
                cursor.execute("""
                    SELECT id FROM news WHERE channel_id = ? AND message_id = ?
                """, (channel_id, message_id))
                row = cursor.fetchone()
                return row['id'] if row else None
            return None
        except sqlite3.Error as e:
            logger.error(f"Error adding news: {e}")
            return None
        finally:
            conn.close()
    
    def get_news_by_period(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get news items within a date period."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT n.id, n.channel_id, n.message_id, n.text, n.date, n.processed,
                   c.username, c.title
            FROM news n
            LEFT JOIN channels c ON n.channel_id = c.channel_id
            WHERE n.date >= ? AND n.date <= ?
            ORDER BY n.date DESC
        """, (start_date, end_date))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_latest_news_date(self, channel_id: int) -> Optional[str]:
        """Get the date of the latest news item for a channel."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT MAX(date) as max_date FROM news WHERE channel_id = ?
        """, (channel_id,))
        row = cursor.fetchone()
        conn.close()
        
        return row['max_date'] if row and row['max_date'] else None
    
    def save_session(self, user_id: int, period_start: str, period_end: str, 
                     aggregated_text: str) -> int:
        """Save aggregation session."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO sessions (user_id, period_start, period_end, aggregated_text, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, period_start, period_end, aggregated_text, datetime.now().isoformat()))
        conn.commit()
        session_id = cursor.lastrowid
        conn.close()
        
        return session_id
    
    # Tags methods
    def create_tag(self, name: str) -> Optional[int]:
        """Create a tag and return its ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Normalize tag name (lowercase, strip)
            name = name.lower().strip()
            cursor.execute("""
                INSERT OR IGNORE INTO tags (name, created_at)
                VALUES (?, ?)
            """, (name, datetime.now().isoformat()))
            conn.commit()
            
            # Get tag ID
            cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row['id'] if row else None
        except sqlite3.Error as e:
            logger.error(f"Error creating tag: {e}")
            return None
        finally:
            conn.close()
    
    def get_tag_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get tag by name."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        name = name.lower().strip()
        cursor.execute("SELECT id, name, created_at FROM tags WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_tag_by_id(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """Get tag by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name, created_at FROM tags WHERE id = ?", (tag_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_all_tags(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all tags, ordered by usage."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT t.id, t.name, t.created_at, COUNT(nt.news_id) as usage_count
            FROM tags t
            LEFT JOIN news_tags nt ON t.id = nt.tag_id
            GROUP BY t.id
            ORDER BY usage_count DESC, t.name ASC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def add_tag_to_news(self, news_id: int, tag_id: int) -> bool:
        """Add tag to news item."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO news_tags (news_id, tag_id)
                VALUES (?, ?)
            """, (news_id, tag_id))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error adding tag to news: {e}")
            return False
        finally:
            conn.close()
    
    def remove_tag_from_news(self, news_id: int, tag_id: int) -> bool:
        """Remove tag from news item."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM news_tags WHERE news_id = ? AND tag_id = ?", (news_id, tag_id))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error removing tag from news: {e}")
            return False
        finally:
            conn.close()
    
    def get_news_tags(self, news_id: int) -> List[Dict[str, Any]]:
        """Get all tags for a news item."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT t.id, t.name, t.created_at
            FROM tags t
            JOIN news_tags nt ON t.id = nt.tag_id
            WHERE nt.news_id = ?
            ORDER BY t.name
        """, (news_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_news_by_tag(self, tag_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get news items by tag."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT n.id, n.channel_id, n.message_id, n.text, n.date, n.processed,
                   c.username, c.title
            FROM news n
            JOIN news_tags nt ON n.id = nt.news_id
            LEFT JOIN channels c ON n.channel_id = c.channel_id
            WHERE nt.tag_id = ?
            ORDER BY n.date DESC
            LIMIT ?
        """, (tag_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def mark_tags_generated(self, news_id: int):
        """Mark that tags have been generated for a news item."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE news SET tags_generated = 1 WHERE id = ?", (news_id,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error marking tags as generated: {e}")
        finally:
            conn.close()
    
    def get_news_without_tags(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get news items that don't have tags generated yet."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT n.id, n.channel_id, n.message_id, n.text, n.date, n.processed,
                   c.username, c.title
            FROM news n
            LEFT JOIN channels c ON n.channel_id = c.channel_id
            WHERE n.tags_generated = 0
            ORDER BY n.date DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    # Statistics methods
    def get_channel_stats(self, channel_id: int) -> Dict[str, Any]:
        """Get statistics for a channel."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Total news count
        cursor.execute("SELECT COUNT(*) as total FROM news WHERE channel_id = ?", (channel_id,))
        total_row = cursor.fetchone()
        total = total_row['total'] if total_row else 0
        
        # Latest news date
        latest_date = self.get_latest_news_date(channel_id)
        
        # News count by period
        from datetime import timedelta
        now = datetime.now()
        day_ago = (now - timedelta(days=1)).isoformat()
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()
        
        cursor.execute("SELECT COUNT(*) as count FROM news WHERE channel_id = ? AND date >= ?", 
                      (channel_id, day_ago))
        day_row = cursor.fetchone()
        day_count = day_row['count'] if day_row else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM news WHERE channel_id = ? AND date >= ?", 
                      (channel_id, week_ago))
        week_row = cursor.fetchone()
        week_count = week_row['count'] if week_row else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM news WHERE channel_id = ? AND date >= ?", 
                      (channel_id, month_ago))
        month_row = cursor.fetchone()
        month_count = month_row['count'] if month_row else 0
        
        conn.close()
        
        return {
            'total': total,
            'latest_date': latest_date,
            'day_count': day_count,
            'week_count': week_count,
            'month_count': month_count
        }
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get global statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Total channels
        cursor.execute("SELECT COUNT(*) as total FROM channels")
        channels_row = cursor.fetchone()
        channels_count = channels_row['total'] if channels_row else 0
        
        # Total news
        cursor.execute("SELECT COUNT(*) as total FROM news")
        news_row = cursor.fetchone()
        news_count = news_row['total'] if news_row else 0
        
        # Total tags
        cursor.execute("SELECT COUNT(*) as total FROM tags")
        tags_row = cursor.fetchone()
        tags_count = tags_row['total'] if tags_row else 0
        
        # Latest news date
        cursor.execute("SELECT MAX(date) as max_date FROM news")
        latest_row = cursor.fetchone()
        latest_date = latest_row['max_date'] if latest_row and latest_row['max_date'] else None
        
        conn.close()
        
        return {
            'channels_count': channels_count,
            'news_count': news_count,
            'tags_count': tags_count,
            'latest_date': latest_date
        }
    
    def get_news_count_by_channel(self, channel_id: int, days: int = None) -> int:
        """Get news count for a channel within specified days."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if days:
            from datetime import timedelta
            start_date = (datetime.now() - timedelta(days=days)).isoformat()
            cursor.execute("""
                SELECT COUNT(*) as count FROM news 
                WHERE channel_id = ? AND date >= ?
            """, (channel_id, start_date))
        else:
            cursor.execute("SELECT COUNT(*) as count FROM news WHERE channel_id = ?", (channel_id,))
        
        row = cursor.fetchone()
        count = row['count'] if row else 0
        conn.close()
        
        return count
    
    def update_channel_source_type(
        self, 
        channel_id: int, 
        source_type: str, 
        source_config: Dict[str, Any] = None
    ) -> bool:
        """
        Update channel source type and configuration.
        
        Args:
            channel_id: Channel ID
            source_type: Source type ('telegram_bot', 'telethon', 'web', 'rss')
            source_config: Optional configuration dict (will be stored as JSON)
            
        Returns:
            True if successful, False otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Update source_type in channels table
            cursor.execute("""
                UPDATE channels SET source_type = ? WHERE channel_id = ?
            """, (source_type, channel_id))
            
            # Update or insert source configuration
            config_json = json.dumps(source_config) if source_config else None
            now = datetime.now().isoformat()
            
            cursor.execute("""
                INSERT INTO sources (channel_id, source_type, source_config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_config = excluded.source_config,
                    updated_at = excluded.updated_at
            """, (channel_id, source_type, config_json, now, now))
            
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating channel source type: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_channels_by_source_type(self, source_type: str) -> List[Dict[str, Any]]:
        """
        Get all channels with specified source type.
        
        Args:
            source_type: Source type to filter by
            
        Returns:
            List of channel dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT channel_id, username, title, added_date, 
                   COALESCE(source_type, 'telegram_bot') as source_type
            FROM channels 
            WHERE COALESCE(source_type, 'telegram_bot') = ?
        """, (source_type,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_channel_source_config(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """
        Get channel source configuration.
        
        Args:
            channel_id: Channel ID
            
        Returns:
            Dict with source_type and source_config, or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Try to get from sources table first
        cursor.execute("""
            SELECT source_type, source_config FROM sources WHERE channel_id = ?
        """, (channel_id,))
        row = cursor.fetchone()
        
        if row:
            source_type = row['source_type']
            source_config = json.loads(row['source_config']) if row['source_config'] else {}
            conn.close()
            return {'source_type': source_type, 'source_config': source_config}
        
        # Fallback to channels table
        cursor.execute("""
            SELECT COALESCE(source_type, 'telegram_bot') as source_type 
            FROM channels WHERE channel_id = ?
        """, (channel_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {'source_type': row['source_type'], 'source_config': {}}
        
        return None

    def set_setting(self, key: str, value: Any) -> bool:
        """Persist an application setting as JSON."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error saving setting {key}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read an application setting."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return row["value"]

    # ---- Posting bots ----------------------------------------------------
    def list_bots(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, label, kind, token, default_chat_id, enabled,
                   created_at, updated_at
            FROM posting_bots
            ORDER BY id ASC
        """)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        for row in rows:
            row["enabled"] = bool(row["enabled"])
            row["token_set"] = bool(row.get("token"))
        return rows

    def get_bot(self, bot_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, label, kind, token, default_chat_id, enabled,
                   created_at, updated_at
            FROM posting_bots WHERE id = ?
        """, (bot_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        record = dict(row)
        record["enabled"] = bool(record["enabled"])
        record["token_set"] = bool(record.get("token"))
        return record

    def create_bot(
        self,
        label: str,
        kind: str = "bot_api",
        token: Optional[str] = None,
        default_chat_id: Optional[str] = None,
        enabled: bool = True,
    ) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO posting_bots
                (label, kind, token, default_chat_id, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (label, kind, token, default_chat_id, 1 if enabled else 0, now, now))
        conn.commit()
        bot_id = cursor.lastrowid
        conn.close()
        return int(bot_id)

    def update_bot(self, bot_id: int, **fields: Any) -> bool:
        allowed = {"label", "kind", "token", "default_chat_id", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        updates["updated_at"] = datetime.now().isoformat()
        columns = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [bot_id]

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE posting_bots SET {columns} WHERE id = ?", params)
        conn.commit()
        changed = cursor.rowcount > 0
        conn.close()
        return changed

    def delete_bot(self, bot_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM posting_bots WHERE id = ?", (bot_id,))
        conn.commit()
        removed = cursor.rowcount > 0
        conn.close()
        return removed

    # ---- LLM prompts -----------------------------------------------------
    def list_prompts(self, task: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if task:
            cursor.execute("""
                SELECT id, task, name, system_prompt, user_template, is_active,
                       created_at, updated_at
                FROM llm_prompts WHERE task = ?
                ORDER BY is_active DESC, name ASC
            """, (task,))
        else:
            cursor.execute("""
                SELECT id, task, name, system_prompt, user_template, is_active,
                       created_at, updated_at
                FROM llm_prompts
                ORDER BY task ASC, is_active DESC, name ASC
            """)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        for row in rows:
            row["is_active"] = bool(row["is_active"])
        return rows

    def get_active_prompt(self, task: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, task, name, system_prompt, user_template, is_active
            FROM llm_prompts WHERE task = ? AND is_active = 1
            LIMIT 1
        """, (task,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        record = dict(row)
        record["is_active"] = bool(record["is_active"])
        return record

    def upsert_prompt(
        self,
        task: str,
        name: str,
        system_prompt: str,
        user_template: str,
        is_active: bool = False,
    ) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO llm_prompts
                (task, name, system_prompt, user_template, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task, name) DO UPDATE SET
                system_prompt = excluded.system_prompt,
                user_template = excluded.user_template,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
        """, (task, name, system_prompt, user_template, 1 if is_active else 0, now, now))
        if is_active:
            cursor.execute("""
                UPDATE llm_prompts SET is_active = 0
                WHERE task = ? AND name <> ?
            """, (task, name))
        conn.commit()
        cursor.execute(
            "SELECT id FROM llm_prompts WHERE task = ? AND name = ?",
            (task, name),
        )
        row = cursor.fetchone()
        conn.close()
        return int(row["id"]) if row else 0

    def set_active_prompt(self, prompt_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT task FROM llm_prompts WHERE id = ?", (prompt_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
        task = row["task"]
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE llm_prompts SET is_active = 0, updated_at = ? WHERE task = ?",
            (now, task),
        )
        cursor.execute(
            "UPDATE llm_prompts SET is_active = 1, updated_at = ? WHERE id = ?",
            (now, prompt_id),
        )
        conn.commit()
        conn.close()
        return True

    def delete_prompt(self, prompt_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM llm_prompts WHERE id = ?", (prompt_id,))
        conn.commit()
        removed = cursor.rowcount > 0
        conn.close()
        return removed

    # ---- Source groups ---------------------------------------------------
    def list_source_groups(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT g.id, g.name, g.color, g.created_at,
                   COUNT(m.channel_id) AS member_count
            FROM source_groups g
            LEFT JOIN source_group_members m ON m.group_id = g.id
            GROUP BY g.id ORDER BY g.name
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def create_source_group(self, name: str, color: str = "#5dd2a2") -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO source_groups (name, color, created_at) VALUES (?, ?, ?)",
            (name, color, datetime.now().isoformat()),
        )
        conn.commit()
        gid = cur.lastrowid
        conn.close()
        return int(gid)

    def rename_source_group(self, group_id: int, name: Optional[str], color: Optional[str]) -> bool:
        fields = []
        params: List[Any] = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if color is not None:
            fields.append("color = ?")
            params.append(color)
        if not fields:
            return False
        params.append(group_id)
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(f"UPDATE source_groups SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def delete_source_group(self, group_id: int) -> bool:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM source_groups WHERE id = ?", (group_id,))
        conn.commit()
        removed = cur.rowcount > 0
        conn.close()
        return removed

    def add_sources_to_group(self, group_id: int, channel_ids: List[int]) -> int:
        if not channel_ids:
            return 0
        conn = self._get_connection()
        cur = conn.cursor()
        now = datetime.now().isoformat()
        added = 0
        for ch_id in channel_ids:
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO source_group_members (group_id, channel_id, added_at) VALUES (?, ?, ?)",
                    (group_id, ch_id, now),
                )
                added += cur.rowcount
            except sqlite3.Error:
                continue
        conn.commit()
        conn.close()
        return added

    def remove_sources_from_group(self, group_id: int, channel_ids: List[int]) -> int:
        if not channel_ids:
            return 0
        conn = self._get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" * len(channel_ids))
        cur.execute(
            f"DELETE FROM source_group_members WHERE group_id = ? AND channel_id IN ({placeholders})",
            (group_id, *channel_ids),
        )
        conn.commit()
        removed = cur.rowcount
        conn.close()
        return removed

    def get_group_channel_ids(self, group_id: int) -> List[int]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id FROM source_group_members WHERE group_id = ?",
            (group_id,),
        )
        rows = [row["channel_id"] for row in cur.fetchall()]
        conn.close()
        return rows

    def get_groups_for_channel(self, channel_id: int) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT g.id, g.name, g.color
            FROM source_groups g
            JOIN source_group_members m ON m.group_id = g.id
            WHERE m.channel_id = ?
            ORDER BY g.name
        """, (channel_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ---- Posting targets -------------------------------------------------
    def list_bot_targets(self, bot_id: int) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, bot_id, chat_id, title, created_at FROM posting_targets WHERE bot_id = ? ORDER BY id",
            (bot_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def add_bot_target(self, bot_id: int, chat_id: str, title: Optional[str] = None) -> Optional[int]:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO posting_targets (bot_id, chat_id, title, created_at) VALUES (?, ?, ?, ?)",
                (bot_id, chat_id, title, datetime.now().isoformat()),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def remove_bot_target(self, target_id: int) -> bool:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM posting_targets WHERE id = ?", (target_id,))
        conn.commit()
        removed = cur.rowcount > 0
        conn.close()
        return removed

    def update_bot_identity(
        self, bot_id: int, tg_id: Optional[int], username: Optional[str], first_name: Optional[str]
    ) -> bool:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE posting_bots
            SET bot_id_telegram = COALESCE(?, bot_id_telegram),
                bot_username    = COALESCE(?, bot_username),
                bot_first_name  = COALESCE(?, bot_first_name),
                updated_at      = ?
            WHERE id = ?
            """,
            (tg_id, username, first_name, datetime.now().isoformat(), bot_id),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    # ---- Audit log (Sprint 3 surface, written from middleware) ----------
    def append_audit(
        self, actor: str, action: str, payload: Optional[Dict[str, Any]], ip: Optional[str] = None
    ) -> None:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_log (actor, action, payload, ip, at) VALUES (?, ?, ?, ?, ?)",
            (actor, action, json.dumps(payload, ensure_ascii=False) if payload else None, ip, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def list_audit(self, limit: int = 200) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, actor, action, payload, ip, at FROM audit_log ORDER BY at DESC LIMIT ?",
            (limit,),
        )
        rows = []
        for r in cur.fetchall():
            entry = dict(r)
            if entry.get("payload"):
                try:
                    entry["payload"] = json.loads(entry["payload"])
                except (TypeError, json.JSONDecodeError):
                    pass
            rows.append(entry)
        conn.close()
        return rows

    # ---- News count by hour (dashboard sparkline) -----------------------
    def news_count_by_hour(self, hours: int = 24) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        start = (datetime.now() - timedelta(hours=hours)).isoformat()
        cur.execute(
            """
            SELECT substr(date, 1, 13) AS hour, COUNT(*) AS count
            FROM news WHERE date >= ?
            GROUP BY hour ORDER BY hour
            """,
            (start,),
        )
        rows = [{"hour": r["hour"], "count": r["count"]} for r in cur.fetchall()]
        conn.close()
        return rows

    # ---- Pipelines -------------------------------------------------------
    def list_pipelines(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, group_name, enabled, schedule_cron, created_at, updated_at
            FROM pipelines ORDER BY group_name, name
        """)
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            row["enabled"] = bool(row["enabled"])
            cur.execute(
                "SELECT id, position, type, params FROM pipeline_steps WHERE pipeline_id = ? ORDER BY position",
                (row["id"],),
            )
            row["steps"] = [
                {
                    "id": s["id"],
                    "position": s["position"],
                    "type": s["type"],
                    "params": json.loads(s["params"]) if s["params"] else {},
                }
                for s in cur.fetchall()
            ]
            cur.execute(
                "SELECT id, status, started_at, finished_at FROM pipeline_runs WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT 5",
                (row["id"],),
            )
            row["recent_runs"] = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_pipeline(self, pipeline_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, group_name, enabled, schedule_cron, created_at, updated_at
            FROM pipelines WHERE id = ?
        """, (pipeline_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        out = dict(row)
        out["enabled"] = bool(out["enabled"])
        cur.execute(
            "SELECT id, position, type, params FROM pipeline_steps WHERE pipeline_id = ? ORDER BY position",
            (pipeline_id,),
        )
        out["steps"] = [
            {
                "id": s["id"],
                "position": s["position"],
                "type": s["type"],
                "params": json.loads(s["params"]) if s["params"] else {},
            }
            for s in cur.fetchall()
        ]
        conn.close()
        return out

    def upsert_pipeline(
        self,
        pipeline_id: Optional[int],
        name: str,
        group_name: str,
        enabled: bool,
        schedule_cron: Optional[str],
        steps: List[Dict[str, Any]],
    ) -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        now = datetime.now().isoformat()
        if pipeline_id:
            cur.execute("""
                UPDATE pipelines
                SET name = ?, group_name = ?, enabled = ?, schedule_cron = ?, updated_at = ?
                WHERE id = ?
            """, (name, group_name, 1 if enabled else 0, schedule_cron, now, pipeline_id))
            cur.execute("DELETE FROM pipeline_steps WHERE pipeline_id = ?", (pipeline_id,))
        else:
            cur.execute("""
                INSERT INTO pipelines (name, group_name, enabled, schedule_cron, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, group_name, 1 if enabled else 0, schedule_cron, now, now))
            pipeline_id = cur.lastrowid

        for idx, step in enumerate(steps):
            cur.execute("""
                INSERT INTO pipeline_steps (pipeline_id, position, type, params)
                VALUES (?, ?, ?, ?)
            """, (
                pipeline_id,
                idx,
                step.get("type", ""),
                json.dumps(step.get("params") or {}, ensure_ascii=False),
            ))
        conn.commit()
        conn.close()
        return int(pipeline_id)

    def delete_pipeline(self, pipeline_id: int) -> bool:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM pipelines WHERE id = ?", (pipeline_id,))
        conn.commit()
        removed = cur.rowcount > 0
        conn.close()
        return removed

    # ---- Pipeline runs ---------------------------------------------------
    def create_run(self, pipeline_id: int, trigger: str = "manual") -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_runs (pipeline_id, status, trigger, started_at)
            VALUES (?, 'running', ?, ?)
        """, (pipeline_id, trigger, datetime.now().isoformat()))
        conn.commit()
        run_id = cur.lastrowid
        conn.close()
        return int(run_id)

    def finish_run(
        self,
        run_id: int,
        status: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE pipeline_runs
            SET status = ?, finished_at = ?, output = ?, error = ?
            WHERE id = ?
        """, (
            status,
            datetime.now().isoformat(),
            json.dumps(output, ensure_ascii=False) if output else None,
            error,
            run_id,
        ))
        conn.commit()
        conn.close()

    def add_step_run(
        self,
        run_id: int,
        step_id: Optional[int],
        position: int,
        type_: str,
        status: str,
        started_at: str,
        finished_at: Optional[str],
        input_data: Optional[Dict[str, Any]],
        output_data: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_step_runs
                (run_id, step_id, position, type, status, started_at, finished_at, input, output, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, step_id, position, type_, status, started_at, finished_at,
            json.dumps(input_data, ensure_ascii=False) if input_data else None,
            json.dumps(output_data, ensure_ascii=False) if output_data else None,
            error,
        ))
        conn.commit()
        sr_id = cur.lastrowid
        conn.close()
        return int(sr_id)

    def list_runs(self, pipeline_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        if pipeline_id:
            cur.execute("""
                SELECT r.id, r.pipeline_id, p.name as pipeline_name, r.status, r.trigger,
                       r.started_at, r.finished_at, r.error
                FROM pipeline_runs r
                LEFT JOIN pipelines p ON p.id = r.pipeline_id
                WHERE r.pipeline_id = ?
                ORDER BY r.started_at DESC LIMIT ?
            """, (pipeline_id, limit))
        else:
            cur.execute("""
                SELECT r.id, r.pipeline_id, p.name as pipeline_name, r.status, r.trigger,
                       r.started_at, r.finished_at, r.error
                FROM pipeline_runs r
                LEFT JOIN pipelines p ON p.id = r.pipeline_id
                ORDER BY r.started_at DESC LIMIT ?
            """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_run_detail(self, run_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.id, r.pipeline_id, p.name as pipeline_name, r.status, r.trigger,
                   r.started_at, r.finished_at, r.error, r.output
            FROM pipeline_runs r
            LEFT JOIN pipelines p ON p.id = r.pipeline_id
            WHERE r.id = ?
        """, (run_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        out = dict(row)
        if out.get("output"):
            try:
                out["output"] = json.loads(out["output"])
            except (TypeError, json.JSONDecodeError):
                pass
        cur.execute("""
            SELECT id, step_id, position, type, status, started_at, finished_at,
                   input, output, error
            FROM pipeline_step_runs WHERE run_id = ? ORDER BY position
        """, (run_id,))
        steps = []
        for s in cur.fetchall():
            entry = dict(s)
            for k in ("input", "output"):
                if entry.get(k):
                    try:
                        entry[k] = json.loads(entry[k])
                    except (TypeError, json.JSONDecodeError):
                        pass
            steps.append(entry)
        out["steps"] = steps
        conn.close()
        return out

    # ---- News helpers used by pipeline steps -----------------------------
    def get_news_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        conn = self._get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        cur.execute(f"""
            SELECT n.id, n.channel_id, n.message_id, n.text, n.date, n.processed,
                   c.username, c.title
            FROM news n
            LEFT JOIN channels c ON n.channel_id = c.channel_id
            WHERE n.id IN ({placeholders})
            ORDER BY n.date DESC
        """, tuple(ids))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_news_ids_by_period(self, start_date: str, end_date: str) -> List[int]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM news WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        rows = [row["id"] for row in cur.fetchall()]
        conn.close()
        return rows

    # ---- News media (stage D) --------------------------------------------
    def add_news_media(
        self,
        news_id: int,
        url: Optional[str],
        kind: str = "image",
        local_path: Optional[str] = None,
        mime: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[int]:
        if not url and not local_path:
            return None
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO news_media (news_id, kind, url, local_path, mime, width, height, downloaded, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (news_id, kind, url, local_path, mime, width, height, 1 if local_path else 0, datetime.now().isoformat()))
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.Error as e:
            logger.error(f"Error adding news media: {e}")
            return None
        finally:
            conn.close()

    def get_media_for_news(self, news_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not news_ids:
            return {}
        conn = self._get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" * len(news_ids))
        cur.execute(f"""
            SELECT id, news_id, kind, url, local_path, mime, width, height
            FROM news_media WHERE news_id IN ({placeholders})
            ORDER BY id
        """, tuple(news_ids))
        media: Dict[int, List[Dict[str, Any]]] = {}
        for row in cur.fetchall():
            media.setdefault(row["news_id"], []).append(dict(row))
        conn.close()
        return media

    def get_settings(self) -> Dict[str, Any]:
        """Read all application settings."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT key, value FROM app_settings ORDER BY key")
        rows = cursor.fetchall()
        conn.close()

        settings: Dict[str, Any] = {}
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                settings[row["key"]] = row["value"]
        return settings
