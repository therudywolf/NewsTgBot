"""Database module for storing channels, news, and sessions."""
import sqlite3
import json
import logging
from datetime import datetime
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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
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

