"""Migration script to add source_type to existing channels."""
import sqlite3
import logging
import sys
import os

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Migrate database to add source_type column."""
    db_path = config.DATABASE_PATH
    
    logger.info(f"Starting migration for database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(channels)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'source_type' in columns:
            logger.info("Column source_type already exists. Migration not needed.")
            conn.close()
            return
        
        # Add source_type column with default value
        logger.info("Adding source_type column to channels table...")
        cursor.execute("""
            ALTER TABLE channels ADD COLUMN source_type TEXT DEFAULT 'telegram_bot'
        """)
        
        # Update existing rows to have default value
        cursor.execute("""
            UPDATE channels SET source_type = 'telegram_bot' WHERE source_type IS NULL
        """)
        
        # Create sources table if it doesn't exist
        logger.info("Creating sources table if not exists...")
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
            CREATE INDEX IF NOT EXISTS idx_sources_channel 
            ON sources(channel_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sources_type 
            ON sources(source_type)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        conn.commit()
        
        # Count migrated channels
        cursor.execute("SELECT COUNT(*) FROM channels")
        count = cursor.fetchone()[0]
        
        logger.info(f"Migration completed successfully. {count} channels migrated.")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        migrate()
        logger.info("Migration completed successfully!")
    except Exception as e:
        logger.info(f"Migration failed: {e}")
        sys.exit(1)

