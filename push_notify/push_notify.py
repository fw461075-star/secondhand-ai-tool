"""
推送通知模块
支持 Server酱（微信推送）和企业微信机器人
订阅物品命中时，推送到用户手机
"""

import os
import json
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_config.json")


def load_config():
    """加载推送配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config):
    """保存推送配置"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def push_serverchan(title, content, sckey):
    """
    Server酱推送（微信）
    https://sct.ftqq.com/
    """
    try:
        data = urllib.parse.urlencode({
            "title": title[:32],
            "desp": content
        }).encode("utf-8")
        url = f"https://sctapi.ftqq.com/{sckey}.send"
        req = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result.get("code") == 0
    except Exception as e:
        print(f"[推送] Server酱失败: {e}")
        return False


def push_wechat_work(title, content, webhook):
    """
    企业微信机器人推送
    https://work.weixin.qq.com/help?person_id=1&doc_id=13376
    """
    try:
        data = json.dumps({
            "msgtype": "text",
            "text": {
                "content": f"【{title}】\n{content}"
            }
        }).encode("utf-8")
        req = urllib.request.Request(webhook, data=data, headers={
            "Content-Type": "application/json"
        })
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result.get("errcode") == 0
    except Exception as e:
        print(f"[推送] 企业微信失败: {e}")
        return False


def push_notification(title, content):
    """
    根据配置自动选择推送渠道
    """
    config = load_config()
    
    # Server酱
    sckey = config.get("serverchan_sckey", "")
    if sckey:
        return push_serverchan(title, content, sckey)
    
    # 企业微信
    webhook = config.get("wechat_webhook", "")
    if webhook:
        return push_wechat_work(title, content, webhook)
    
    return False


def notify_want_hit(item, matched_word, text, group_name, sender_name):
    """
    订阅物品命中时推送通知
    """
    title = f"二手交易提醒: {item}"
    content = (
        f"你想找的 **{item}** 出现了！\n\n"
        f"- 匹配: {matched_word}\n"
        f"- 群: {group_name}\n"
        f"- 发送者: {sender_name}\n"
        f"- 内容: {text[:200]}\n"
    )
    return push_notification(title, content)


if __name__ == "__main__":
    # 测试
    config = load_config()
    if not config.get("serverchan_sckey") and not config.get("wechat_webhook"):
        print("未配置推送渠道！")
        print("请编辑 push_config.json，填入以下任一配置：")
        print('  {"serverchan_sckey": "你的SCKey"}')
        print('  {"wechat_webhook": "企业微信机器人webhook"}')
    else:
        ok = push_notification("测试", "这是一条测试推送")
        print(f"推送{'成功' if ok else '失败'}")
