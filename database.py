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
                UNIQUE(channel_id, message_id)
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
        
        conn.commit()
        conn.close()
    
    def add_channel(self, channel_id: int, username: str = None, title: str = None) -> bool:
        """Add a channel to the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO channels (channel_id, username, title, added_date)
                VALUES (?, ?, ?, ?)
            """, (channel_id, username, title, datetime.now().isoformat()))
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
            # Also delete associated news
            cursor.execute("DELETE FROM news WHERE channel_id = ?", (channel_id,))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error removing channel: {e}")
            return False
        finally:
            conn.close()
    
    def get_all_channels(self) -> List[Dict[str, Any]]:
        """Get all channels from the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT channel_id, username, title, added_date FROM channels")
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_channel_by_id(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get channel by channel_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT channel_id, username, title, added_date 
            FROM channels WHERE channel_id = ?
        """, (channel_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def add_news(self, channel_id: int, message_id: int, text: str, date: str) -> bool:
        """Add news item to the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO news (channel_id, message_id, text, date)
                VALUES (?, ?, ?, ?)
            """, (channel_id, message_id, text, date))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error adding news: {e}")
            return False
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

