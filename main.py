import requests
import json
import logging
import time
import asyncio
import telegram
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import colorlog
from fake_useragent import UserAgent
import urllib3
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from asyncio import Queue
import itertools

CONFIG_FILE = "config.json"
PROXY_FILE = "proxies.txt"

# Setup logging with color
log_colors = {
    'DEBUG': 'cyan',
    'INFO': 'white',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'SUCCESS': 'green'
}

formatter = colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
    log_colors=log_colors
)

handler = logging.StreamHandler()
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Adding a custom SUCCESS level between INFO and WARNING
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")

def log_success(message, *args, **kwargs):
    if logger.isEnabledFor(SUCCESS_LEVEL):
        logger._log(SUCCESS_LEVEL, message, args, **kwargs)

logging.success = log_success

def read_config(filename=CONFIG_FILE):
    try:
        with open(filename, 'r') as file:
            config = json.load(file)
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file '{filename}' not found.")
        return {}
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON format in '{filename}'.")
        return {}

def read_proxies(filename=PROXY_FILE):
    proxies = []
    try:
        with open(filename, 'r') as file:
            for line in file:
                proxy = line.strip()
                if proxy:
                    proxies.append(proxy)
    except FileNotFoundError:
        logging.error(f"Proxy file '{filename}' not found.")
    return proxies

def parse_proxy(proxy):
    """Parse proxy string into format for requests."""
    proxy_url = urlparse(proxy)
    if proxy_url.scheme in ['http', 'https', 'socks5']:
        if proxy_url.username and proxy_url.password:
            return {
                'http': f"{proxy_url.scheme}://{proxy_url.username}:{proxy_url.password}@{proxy_url.hostname}:{proxy_url.port}",
                'https': f"{proxy_url.scheme}://{proxy_url.username}:{proxy_url.password}@{proxy_url.hostname}:{proxy_url.port}",
            }
        else:
            return {
                'http': f"{proxy_url.scheme}://{proxy_url.hostname}:{proxy_url.port}",
                'https': f"{proxy_url.scheme}://{proxy_url.hostname}:{proxy_url.port}",
            }
    return {}

def check_proxy(proxy):
    """Check if the proxy is active by sending a request to a test URL."""
    proxies = parse_proxy(proxy)
    test_url = "http://httpbin.org/ip"  # You can change this URL to any service that returns IP
    try:
        response = requests.get(test_url, proxies=proxies, timeout=5)
        if response.status_code == 200:
            logging.success(f"Proxy {proxy} is active.")
            return True
    except requests.RequestException:
        logging.error(f"Proxy {proxy} is inactive.")
    return False

def get_active_proxies():
    """Check all proxies and return a list of active proxies using multithreading."""
    proxies = read_proxies(PROXY_FILE)
    active_proxies = []

    # Create a ThreadPoolExecutor to run proxy checks concurrently
    with ThreadPoolExecutor(max_workers=20) as executor:  # You can adjust max_workers to control the level of concurrency
        futures = [executor.submit(check_proxy, proxy) for proxy in proxies]
        
        # Collect results as they complete
        for future, proxy in zip(futures, proxies):
            if future.result():
                active_proxies.append(proxy)

    if active_proxies:
        logging.success(f"Found {len(active_proxies)} active proxies.")
        return active_proxies
    else:
        logging.error("No active proxies found.")
        return []

def update_proxies_file(active_proxies):
    """Update proxies.txt file with only active proxies."""
    with open(PROXY_FILE, 'w') as file:
        for proxy in active_proxies:
            file.write(f"{proxy}\n")
    logging.success(f"Updated {PROXY_FILE} with {len(active_proxies)} active proxies.")

def create_session(proxy=None):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(pool_connections=10, pool_maxsize=10))
    session.mount('https://', HTTPAdapter(pool_connections=10, pool_maxsize=10))
    if proxy:
        proxies = parse_proxy(proxy)
        logging.info(f"Using proxy: {proxy}")
        session.proxies.update(proxies)
    return session

config = read_config(CONFIG_FILE)
bot_token = config.get("telegram_bot_token")
chat_id = config.get("telegram_chat_id")
use_proxy = config.get("use_proxy", False)
use_telegram = config.get("use_telegram", False)
poll_interval = config.get("poll_interval", 120)  # Default to 120 seconds

if use_telegram and (not bot_token or not chat_id):
    logging.error("Missing 'bot_token' or 'chat_id' in 'config.json'.")
    exit(1)

bot = telegram.Bot(token=bot_token) if use_telegram else None
keepalive_url = "https://www.aeropres.in/chromeapi/dawn/v1/userreward/keepalive"
get_points_url = "https://www.aeropres.in/api/atom/v1/userreferral/getpoint"
extension_id = "fpdkjdnhkakefebpekbdhillbhonfjjp"
_v = "1.0.7"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ua = UserAgent()

def read_account(filename="config.json"):
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
            accounts = data.get("accounts", [])
            return accounts 
    except FileNotFoundError:
        logging.error(f"Config file '{filename}' not found.")
        return []
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON format in '{filename}'.")
        return []

def total_points(headers, session):
    try:
        response = session.get(get_points_url, headers=headers, verify=False)
        response.raise_for_status()

        json_response = response.json()
        if json_response.get("status"):
            reward_point_data = json_response["data"]["rewardPoint"]
            referral_point_data = json_response["data"]["referralPoint"]
            total_points = (
                reward_point_data.get("points", 0) +
                reward_point_data.get("registerpoints", 0) +
                reward_point_data.get("signinpoints", 0) +
                reward_point_data.get("twitter_x_id_points", 0) +
                reward_point_data.get("discordid_points", 0) +
                reward_point_data.get("telegramid_points", 0) +
                reward_point_data.get("bonus_points", 0) +
                referral_point_data.get("commission", 0)
            )
            return total_points
        else:
            logging.warning(f"Warning: {json_response.get('message', 'Unknown error when fetching points')}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching points: {e}")
    return 0

def keep_alive(headers, email, session):
    keepalive_payload = {
        "username": email,
        "extensionid": extension_id,
        "numberoftabs": 0,
        "_v": _v
    }

    headers["User-Agent"] = ua.random

    try:
        response = session.post(keepalive_url, headers=headers, json=keepalive_payload, verify=False)
        response.raise_for_status()

        json_response = response.json()
        if 'message' in json_response:
            return True, json_response['message']
        else:
            return False, "Message not found in response"
    except requests.exceptions.RequestException as e:
        return False, str(e)

# Queue for Telegram messages
message_queue = Queue()

async def telegram_worker():
    while True:
        message = await message_queue.get()
        await telegram_message(message)
        message_queue.task_done()

async def queue_telegram_message(message):
    await message_queue.put(message)

async def telegram_message(message):
    if use_telegram:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            await asyncio.sleep(1)  # Delay of 1 second after sending the message
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")

async def process_account(account, proxy_cycle, active_proxies):
    email = account["email"]
    token = account["token"]
    headers = { 
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": ua.random
    }

    all_failed = True  # Track if all proxies fail

    # Kita iterasi berdasarkan jumlah proxy yang ada dalam daftar active_proxies
    for _ in range(len(active_proxies)):
        proxy = next(proxy_cycle)
        session = create_session(proxy)

        success, status_message = keep_alive(headers, email, session)

        if success:
            points = total_points(headers, session)
            message = (
                "✅ *🌟 Success Notification 🌟* ✅\n\n"
                f"👤 *Account:* {email}\n\n"
                f"💰 *Points Earned:* {points}\n\n"
                f"📢 *Message:* {status_message}\n\n"
                f"🛠️ *Proxy Used:* {proxy}"  # Menambahkan proxy yang digunakan
                "\n\n🤖 *Bot made by https://t.me/AirdropInsiderID*"  # Tautan yang dapat diklik
            )
            await queue_telegram_message(message)
            all_failed = False
            break  # If success, break out of proxy loop to continue with next account
        else:
            logging.error(f"Failed keep alive for {email} with proxy {proxy}. Reason: {status_message}")
    
    if all_failed:
        message = (
            "⚠️ *Failure Notification* ⚠️\n\n"
            f"👤 *Account:* {email}\n\n"
            "❌ *Status:* Keep Alive Failed for All Proxies\n\n"
            "⚙️ *Action Required:* Please check proxy list or account status.\n\n"
            "\n\n🤖 *Bot made by <a href='https://t.me/AirdropInsiderID'>Airdrop Insider ID</a>*"  
        )
        await queue_telegram_message(message)

async def main():
    accounts = read_account()
    active_proxies = get_active_proxies()
    update_proxies_file(active_proxies)
    
    # Create an infinite cycle of proxies
    proxy_cycle = itertools.cycle(active_proxies)

    # Start the Telegram message worker
    asyncio.create_task(telegram_worker())

    # Keep script running indefinitely until user stops
    while True:
        for account in accounts:
            await process_account(account, proxy_cycle, active_proxies)  # Pass active_proxies as argument
        logging.info(f"Waiting {poll_interval} seconds before next cycle.")
        await asyncio.sleep(poll_interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script stopped by user.")
