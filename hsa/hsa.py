import os
import asyncio
import aiohttp
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor
from googletrans import Translator
from telegram import Bot

# 配置信息
API_BASE_URL = "https://api.pearktrue.cn/api/dailyhot/"
NEWS_API_URL = "https://newsapi.org/v2/top-headlines"
NEWS_API_KEY = os.environ["NEWS_API_KEY"]
PLATFROMS = [
    ["哔哩哔哩", "mobileUrl"], ["微博", "url"],
    ["百度贴吧", "url"], ["少数派", "url"],
    ["IT之家", "url"], ["腾讯新闻", "url"],
    ["今日头条", "url"], ["36氪", "url"],
    ["澎湃新闻", "url"], ["百度", "url"],
    ["稀土掘金", "mobileUrl"], ["知乎", "url"]
]

FOREIGN_MEDIA = [
    ["彭博社", "bloomberg"], #["BBC", "bbc-news"]
]

CATEGORIES = [
    ["世界-商业", "business"], ["世界-科学", "science"], ["世界-技术", "technology"], ["世界-综合", "general"]
]

TELEGRAM_BOT_TOKEN = os.environ["BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = '@hot_search_aggregation'
TELEGRAM_GROUP_ID = '-1002699038758'

# 初始化组件
bot = Bot(token=TELEGRAM_BOT_TOKEN)
translator_executor = ThreadPoolExecutor(max_workers=10)
translator = Translator()

def escape_html(text):
    if text is None:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def fetch_data(url, params):
    """异步获取数据"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                return data
        except Exception as e:
            print(f"错误：请求时发生异常：{str(e)}")
            return None

async def fetch_hot_data(platform):
    """获取指定平台的热搜数据"""
    url = f"{API_BASE_URL}?title={platform}"
    data = await fetch_data(url, {})
    if data and data.get("code") == 200:
        return data.get("data", [])
    print(f"警告：{platform} API返回错误：{data.get('message') if data else '未知错误'}")
    return []

async def fetch_news_data(source=None, category=None):
    """获取指定来源或类别的新闻数据"""
    params = {'apiKey': NEWS_API_KEY, 'pageSize': 20}
    if source:
        params['sources'] = source
    if category:
        params['category'] = category
    data = await fetch_data(NEWS_API_URL, params)
    if data and data.get("status") == "ok":
        return data.get("articles", [])
    print(f"警告：{source or category} API返回错误：{data.get('message') if data else '未知错误'}")
    return []

async def translate_text(text):
    """使用线程池执行Google翻译"""
    if not text:
        return text
    
    loop = asyncio.get_event_loop()
    try:
        # 在单独的线程中执行同步翻译操作
        translated = await loop.run_in_executor(
            translator_executor,
            lambda: translator.translate(text, dest='zh-cn').text
        )
        return translated
    except Exception as e:
        print(f"翻译错误：{str(e)}，原文：{text}")
        return text

async def format_data(data_list, url_key, is_news=False):
    """格式化数据为可读文本，并添加序号""" 
    formatted_data = []
    for index, item in enumerate(data_list[:10], start=1):
        # 翻译处理
        title = item.get('title', '无标题')
        if is_news and title != '无标题':
            title = await translate_text(title)
        
        title = escape_html(title)
        url = item.get(url_key, '#')
        hot_info = f"<i>{item.get('hot')}🔥</i>" if not is_news and item.get('hot') else ""

        # 描述处理
        desc = item.get('description') or item.get('desc') or ''
        if desc and is_news:
            desc = await translate_text(desc)
        
        desc = escape_html(desc)
        if desc:
            desc = f"\n\n{desc[:150] + '...' if len(desc) > 150 else desc}"

        formatted_string = f"{index}. <a href=\"{url}\">{title}</a>{hot_info}{desc}"
        formatted_data.append(formatted_string)

    return formatted_data

async def send_to_telegram(platform, formatted_data):
    """发送数据到 Telegram 频道并记录消息 ID"""
    top = formatted_data[:10]
    first_hot_search = formatted_data[0] if formatted_data else "无热搜"
    message = f"<b>{escape_html(platform)}</b> 热搜榜单\n" + "\n\n".join(top)
    sent_message = await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode='HTML')

    message_info = {
        'id': sent_message.message_id,
        'name': platform,
        'first_hot_search': first_hot_search
    }
    return message_info

async def main():
    tz = pytz.timezone('Asia/Shanghai')
    current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    init_message = await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=f"北京时间: <b>{current_time}</b>", parse_mode='HTML')
    await bot.pin_chat_message(chat_id=TELEGRAM_CHANNEL_ID, message_id=init_message.message_id)
    await asyncio.sleep(2)

    all_message_info = []

    # 获取国际媒体新闻
    for media in FOREIGN_MEDIA:
        print(f"正在获取：{media[0]}")
        articles = await fetch_news_data(source=media[1])
        if articles:
            formatted_news = await format_data(articles, 'url', is_news=True)
            message_info = await send_to_telegram(media[0], formatted_news)
            all_message_info.append(message_info)
        await asyncio.sleep(2)

    # 获取国内平台热搜
    for platform in PLATFROMS:
        print(f"正在获取：{platform[0]}")
        data = await fetch_hot_data(platform[0])
        if data:
            formatted = await format_data(data, platform[1])
            message_info = await send_to_telegram(platform[0], formatted)
            all_message_info.append(message_info)
        await asyncio.sleep(2)

    # 生成聚合消息
    if all_message_info:
        jump_message = f"北京时间: <b>{current_time}</b>\n\n"
        links = []

        for info in all_message_info:
            link = f"<a href='https://t.me/{TELEGRAM_CHANNEL_ID[1:]}/{info['id']}'>{escape_html('☞ ' + info['name'])}</a>\n\n首条: {info['first_hot_search'][3:]}"
            links.append(link)

        jump_message += "\n\n".join(links)
        share_message = jump_message + "\n\n<b><i>加入我们了解最新热搜！</i></b>"
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=share_message, parse_mode='HTML')

    # 关闭线程池
    translator_executor.shutdown(wait=True)

if __name__ == '__main__':
    asyncio.run(main())