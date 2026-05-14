"""Web parser for parsing Telegram channels via web scraping.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf
Licensed under AGPL-3.0
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import re

from .base import BaseParser
import config
from source_identity import stable_source_id

logger = logging.getLogger(__name__)


class WebParser(BaseParser):
    """Parser for Telegram channels using web scraping."""
    
    def __init__(self):
        """Initialize Web parser."""
        super().__init__()
        self.browser = None
        self._initialized = False
    
    async def _get_browser(self):
        """Get or create browser instance."""
        if self.browser is not None:
            return self.browser
        
        try:
            if config.WEB_PARSER_ENGINE.lower() == 'playwright':
                from playwright.async_api import async_playwright
                
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(
                    headless=config.WEB_PARSER_HEADLESS
                )
                self._playwright = playwright
                self._initialized = True
                return self.browser
            else:
                # Selenium
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                
                options = Options()
                if config.WEB_PARSER_HEADLESS:
                    options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                
                self.browser = webdriver.Chrome(options=options)
                self._selenium_by = By
                self._selenium_ec = EC
                self._selenium_wait = WebDriverWait
                self._initialized = True
                return self.browser
                
        except ImportError as e:
            logger.error(f"Web scraping library not installed: {e}")
            return None
        except Exception as e:
            logger.error(f"Error initializing browser: {e}")
            return None
    
    async def check_availability(self) -> bool:
        """Check if Web parser is available."""
        try:
            if config.WEB_PARSER_ENGINE.lower() == 'playwright':
                from playwright.async_api import async_playwright
                return True
            else:
                from selenium import webdriver
                return True
        except ImportError:
            return False
    
    def _get_channel_url(self, channel_username: str) -> str:
        """
        Get Telegram web URL for a channel.
        
        Args:
            channel_username: Channel username
            
        Returns:
            Telegram web URL
        """
        username = self._normalize_channel_username(channel_username)
        return f"https://t.me/s/{username}"
    
    async def get_channel_info(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a channel from web page.
        
        Args:
            channel_username: Channel username
            
        Returns:
            Dict with channel info or None
        """
        try:
            browser = await self._get_browser()
            if browser is None:
                return None
            
            url = self._get_channel_url(channel_username)
            
            if config.WEB_PARSER_ENGINE.lower() == 'playwright':
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until='networkidle', timeout=config.WEB_PARSER_TIMEOUT * 1000)
                    
                    # Extract channel info
                    title = await page.locator('div.tgme_channel_info_header_title').text_content()
                    title = title.strip() if title else None
                    
                    description = await page.locator('div.tgme_channel_info_description').text_content()
                    description = description.strip() if description else None
                    
                    return {
                        'channel_id': None,  # Web scraping doesn't provide channel_id
                        'username': channel_username,
                        'title': title or channel_username,
                        'description': description or '',
                        'subscribers': None,
                        'is_public': True
                    }
                finally:
                    await page.close()
            else:
                # Selenium
                browser.get(url)
                
                # Wait for page to load
                wait = self._selenium_wait(browser, config.WEB_PARSER_TIMEOUT)
                title_element = wait.until(
                    self._selenium_ec.presence_of_element_located(
                        (self._selenium_by.CSS_SELECTOR, 'div.tgme_channel_info_header_title')
                    )
                )
                
                title = title_element.text.strip() if title_element else None
                
                try:
                    desc_element = browser.find_element(self._selenium_by.CSS_SELECTOR, 'div.tgme_channel_info_description')
                    description = desc_element.text.strip() if desc_element else None
                except:
                    description = None
                
                return {
                    'channel_id': None,
                    'username': channel_username,
                    'title': title or channel_username,
                    'description': description or '',
                    'subscribers': None,
                    'is_public': True
                }
                
        except Exception as e:
            logger.error(f"Error getting web channel info: {e}")
            return None
    
    async def parse_channel(
        self,
        channel_username: str,
        limit: Optional[int] = None,
        days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parse messages from a channel using web scraping.
        
        Args:
            channel_username: Channel username
            limit: Maximum number of messages to fetch
            days: Number of days to look back
            
        Returns:
            Dict with parsing results
        """
        result = {
            'parsed': 0,
            'skipped': 0,
            'errors': 0,
            'messages': []
        }
        
        try:
            browser = await self._get_browser()
            if browser is None:
                result['errors'] = 1
                return result
            
            url = self._get_channel_url(channel_username)
            channel_id = stable_source_id(channel_username, "web")
            
            # Calculate cutoff date if days specified
            cutoff_date = None
            if days:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            if config.WEB_PARSER_ENGINE.lower() == 'playwright':
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until='networkidle', timeout=config.WEB_PARSER_TIMEOUT * 1000)
                    
                    # Scroll to load more messages if needed
                    if limit and limit > 20:
                        scrolls = (limit // 20) + 1
                        for _ in range(scrolls):
                            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                            await page.wait_for_timeout(1000)  # Wait for new content
                    
                    # Extract messages
                    message_elements = await page.locator('div.tgme_widget_message').all()
                    
                    messages_fetched = 0
                    for msg_element in message_elements[:limit] if limit else message_elements:
                        try:
                            # Get message text
                            text_elem = msg_element.locator('div.tgme_widget_message_text')
                            text = await text_elem.text_content()
                            text = text.strip() if text else ""
                            
                            if not text:
                                result['skipped'] += 1
                                continue
                            
                            # Get message date
                            date_elem = msg_element.locator('time.datetime')
                            date_str = await date_elem.get_attribute('datetime')
                            
                            if date_str:
                                try:
                                    msg_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                except:
                                    msg_date = datetime.now()
                            else:
                                msg_date = datetime.now()
                            
                            # Skip if too old
                            compare_date = msg_date
                            if compare_date.tzinfo is None:
                                compare_date = compare_date.replace(tzinfo=timezone.utc)
                            if cutoff_date and compare_date < cutoff_date:
                                continue
                            
                            # Get message ID from data-post attribute or generate from date
                            post_attr = await msg_element.get_attribute('data-post')
                            if post_attr:
                                # Format: channel/message_id
                                parts = post_attr.split('/')
                                message_id = int(parts[-1]) if len(parts) > 1 else stable_source_id(text, "web-message")
                            else:
                                message_id = stable_source_id(f"{text}{msg_date}", "web-message")
                            
                            # Format message
                            msg_dict = {
                                'message_id': message_id,
                                'text': text,
                                'date': self._format_date(msg_date),
                                'channel_id': channel_id
                            }
                            
                            result['messages'].append(msg_dict)
                            result['parsed'] += 1
                            messages_fetched += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing web message: {e}")
                            result['errors'] += 1
                            continue
                finally:
                    await page.close()
                
            else:
                # Selenium
                browser.get(url)
                wait = self._selenium_wait(browser, config.WEB_PARSER_TIMEOUT)
                
                # Scroll to load more if needed
                if limit and limit > 20:
                    scrolls = (limit // 20) + 1
                    for _ in range(scrolls):
                        browser.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                        import time
                        time.sleep(1)
                
                # Extract messages
                message_elements = browser.find_elements(self._selenium_by.CSS_SELECTOR, 'div.tgme_widget_message')
                
                messages_fetched = 0
                for msg_element in (message_elements[:limit] if limit else message_elements):
                    try:
                        # Get message text
                        try:
                            text_elem = msg_element.find_element(self._selenium_by.CSS_SELECTOR, 'div.tgme_widget_message_text')
                            text = text_elem.text.strip()
                        except:
                            text = ""
                        
                        if not text:
                            result['skipped'] += 1
                            continue
                        
                        # Get message date
                        try:
                            date_elem = msg_element.find_element(self._selenium_by.CSS_SELECTOR, 'time.datetime')
                            date_str = date_elem.get_attribute('datetime')
                            if date_str:
                                msg_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            else:
                                msg_date = datetime.now()
                        except:
                            msg_date = datetime.now()
                        
                        # Skip if too old
                        compare_date = msg_date
                        if compare_date.tzinfo is None:
                            compare_date = compare_date.replace(tzinfo=timezone.utc)
                        if cutoff_date and compare_date < cutoff_date:
                            continue
                        
                        # Get message ID
                        post_attr = msg_element.get_attribute('data-post')
                        if post_attr:
                            parts = post_attr.split('/')
                            message_id = int(parts[-1]) if len(parts) > 1 else stable_source_id(text, "web-message")
                        else:
                            message_id = stable_source_id(f"{text}{msg_date}", "web-message")
                        
                        # Format message
                        msg_dict = {
                            'message_id': message_id,
                            'text': text,
                            'date': self._format_date(msg_date),
                            'channel_id': channel_id
                        }
                        
                        result['messages'].append(msg_dict)
                        result['parsed'] += 1
                        messages_fetched += 1
                        
                    except Exception as e:
                        logger.error(f"Error processing web message: {e}")
                        result['errors'] += 1
                        continue
            
            logger.info(f"Web: Completed parsing {channel_username}. "
                       f"Parsed: {result['parsed']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing web channel {channel_username}: {e}", exc_info=True)
            result['errors'] += 1
            return result
    
    async def close(self):
        """Close browser instance."""
        try:
            if self.browser:
                if config.WEB_PARSER_ENGINE.lower() == 'playwright':
                    await self.browser.close()
                    if hasattr(self, '_playwright'):
                        await self._playwright.stop()
                else:
                    self.browser.quit()
        except Exception:
            pass
        finally:
            self.browser = None
            self._initialized = False
