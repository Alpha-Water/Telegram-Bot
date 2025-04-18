import os
import asyncio
import aiohttp
from datetime import datetime
import pytz
from telegram import Bot
import translators as ts
import re

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
    ["彭博社", "bloomberg"], ["BBC", "bbc-news"]
]

CATEGORIES = [
    ["世界-商业", "business"], ["世界-科学", "science"], ["世界-技术", "technology"], ["世界-综合", "general"]
]

TELEGRAM_BOT_TOKEN = os.environ["BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = '@hot_spot_aggregation' # -1002536090782
TELEGRAM_GROUP_ID = '-1002699038758'

bot = Bot(token=TELEGRAM_BOT_TOKEN)
# _ = ts.preaccelerate_and_speedtest()

新增配置项
OLLAMA_API_URL = "http://localhost:11434/api/generate"  # Ollama服务地址
CATEGORY_CHANNELS = {
    "科技": "@tech_channel",
    "财经": "@finance_channel",
    "国际": "@world_channel",
    # 添加更多分类映射
}

# 新增分类函数
async def classify_with_ollama(text):
    prompt = f"""请对以下新闻内容进行分类，仅返回分类结果：
    可选分类：科技、财经、国际、体育、娱乐、健康、教育、军事、其他
    内容：{text[:1000]}  # 控制输入长度
    
    返回格式：{{"category": "分类名称"}}"""
    
    payload = {
        "model": "llama3",  # 根据实际模型调整
        "prompt": prompt,
        "format": "json",
        "stream": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload, timeout=30) as response:
                result = await response.json()
                if 'response' in result:
                    match = re.search(r'{\s*"category":\s*"([^"]+)"\s*}', result['response'])
                    return match.group(1) if match else "其他"
                return "其他"
    except Exception as e:
        print(f"分类失败: {str(e)}")
        return "其他"

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
        print(data)
        return data.get("articles", [])
    print(f"警告：{source or category} API返回错误：{data.get('message') if data else '未知错误'}")
    return []

async def translate_text(text):
    """使用 translators 翻译文本"""
    if text is None:
        return ""
    try:
        translated_text = ts.translate_text(text, translator='caiyun', from_language='en', to_language='zh')
        await asyncio.sleep(2)
        return translated_text
    except Exception as e:
        print(f"翻译错误：{text}，错误信息：{str(e)}")
        return text

async def format_data(data_list, url_key, is_news=False):
    """格式化数据为可读文本，并添加序号""" 
    formatted_data = []
    for index, item in enumerate(data_list[:30], start=1):
        title = item.get('title', '无标题') if not is_news else await translate_text(item.get('title', '无标题'))
        title = title if title is not None else '无标题'
        title = escape_html(title)
        url = item.get(url_key, '#')
        hot_info = f"<i>{item.get('hot')}🔥</i>" if not is_news and item.get('hot') else ""

        if item.get('description'):
            desc = await translate_text(item.get('description'))
        elif item.get('desc'):
            desc = item.get('desc')
        else:
            desc = ''

        if desc:
            desc = desc.replace('\n', '')
            if len(desc) > 150:
                desc = desc[:100] + '……'
            desc = "\n\n" + escape_html(desc) 
        else:
            desc = ""

        formatted_string = f"{index}. <a href=\"{url}\">{title}</a>{hot_info}{desc}"
        formatted_data.append(formatted_string)

    return formatted_data

async def send_to_telegram(platform, formatted_data):
    """发送数据到 Telegram 频道并记录消息 ID"""
    top = formatted_data[:10]
    first_hot_search = formatted_data[0] if formatted_data else "无热搜"
    message = f"<b>{escape_html(platform)}</b> 热点榜单\n" + "\n\n".join(top)
    sent_message = await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode='HTML')

    message_info = {
        'id': sent_message.message_id,
        'name': platform,
        'first_hot_search': first_hot_search  # 记录第一条热搜
    }

    await asyncio.sleep(4)

    # 获取群组中的最新消息
    offset = 0
    forwarded_message_id = None
    sent_time = sent_message.date.timestamp()

    while True:
        updates = await bot.get_updates(offset=offset)
        if not updates:
            break

        for update in updates:
            if update.message and update.message.chat.id == int(TELEGRAM_GROUP_ID):
                if update.message.date.timestamp() > sent_time and update.message.is_automatic_forward:
                    forwarded_message_id = update.message.message_id
                    break
            offset = update.update_id + 1

        if forwarded_message_id is not None:
            break

    if forwarded_message_id is None:
        print("未找到转发的消息 ID")
        return message_info  # 返回消息信息

    for i in range(10, len(formatted_data), 10):
        group = formatted_data[i:i + 10]
        comment_message = "\n\n".join(group)
        await bot.send_message(chat_id=TELEGRAM_GROUP_ID, text=comment_message, parse_mode='HTML', reply_to_message_id=forwarded_message_id)
        await asyncio.sleep(2)

    # 返回记录的消息信息
    return message_info

async def process_articles(articles, source_name):
    categorized = defaultdict(list)
    for article in articles:
        # 组合分类依据
        classification_text = f"{article.get('title','')} {article.get('description','')}"
        category = await classify_with_ollama(classification_text)
        
        # 格式化条目
        formatted = await format_entry(article)
        categorized[category].append(formatted)
    
    # 分频道发送
    for category, items in categorized.items():
        channel_id = CATEGORY_CHANNELS.get(category, "@default_channel")
        await send_to_category_channel(channel_id, source_name, category, items)

async def send_to_category_channel(channel_id, source, category, items):
    message = f"【{source} - {category}】最新动态：\n\n" + "\n\n".join(items[:15])
    await bot.send_message(chat_id=channel_id, text=message, parse_mode='HTML')
    await asyncio.sleep(2)

async def main():
    tz = pytz.timezone('Asia/Shanghai')
    current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    init_message = await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=f"北京时间: <b>{current_time}</b>", parse_mode='HTML')
    await bot.pin_chat_message(chat_id=TELEGRAM_CHANNEL_ID, message_id=init_message.message_id)
    await asyncio.sleep(2)

    all_message_info = []  # 用于记录所有热搜榜单的消息 ID 和名称

    for media in FOREIGN_MEDIA:
        print(f"正在获取：{media[0]}")
        articles = await fetch_news_data(source=media[1])
        if articles:
            formatted_news = await format_data(articles, 'url', is_news=True)
            message_info = await send_to_telegram(media[0], formatted_news)
            all_message_info.append(message_info)
        await asyncio.sleep(2)

    for category in CATEGORIES:
        print(f"正在获取：{category[0]}")
        articles = await fetch_news_data(category=category[1])
        if articles:
            formatted_news = await format_data(articles, 'url', is_news=True)
            message_info = await send_to_telegram(category[0], formatted_news)
            all_message_info.append(message_info)
        await asyncio.sleep(2)

    for platform in PLATFROMS:
        print(f"正在获取：{platform[0]}")
        data = await fetch_hot_data(platform[0])
        if data:
            formatted = await format_data(data, platform[1])
            message_info = await send_to_telegram(platform[0], formatted)
            await process_articles(data, platform[0])
            all_message_info.append(message_info)
        await asyncio.sleep(2)

    if all_message_info:
        jump_message = f"北京时间: <b>{current_time}</b>\n<b>-快-速-预-览-</b>\n\n"
        links = []

        for info in all_message_info:
            link = f"<b><a href='https://t.me/{TELEGRAM_CHANNEL_ID[1:]}/{info['id']}'>☞  {escape_html(info['name'])} 榜单</a></b>\n\n首条: {info['first_hot_search'][3:]}"
            links.append(link)

        jump_message += "\n\n".join(links)
        share_message = jump_message + "\n\n<i>自动更新，<a href='https://github.com/Lifelong-Learning-Water/Telegram-Bot'>开源项目</a>，<b><a href='https://t.me/hot_search_aggregation'>热点聚合</a>！</b></i>"
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=share_message, parse_mode='HTML')

if __name__ == '__main__':
    asyncio.run(main())