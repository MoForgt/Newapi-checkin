# -*- coding: utf-8 -*-
"""
钉钉通知模块
用于发送签到结果到钉钉群机器人
"""

import hmac
import hashlib
import re
import base64
import time
import urllib.parse
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

try:
    import requests
except ImportError:
    requests = None

from notifier import format_money


class DingTalkNotifier:
    """钉钉机器人通知类"""
    
    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        初始化钉钉通知器
        
        Args:
            webhook_url: 钉钉机器人的 Webhook URL
            secret: 可选的签名密钥（如果机器人开启了加签安全设置）
        """
        self.webhook_url = webhook_url
        self.secret = secret
    
    def _get_sign(self) -> tuple:
        """
        生成签名
        
        Returns:
            (timestamp, sign) 元组
        """
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return timestamp, sign
    
    def _get_url(self) -> str:
        """
        获取完整的请求 URL（包含签名参数）
        
        Returns:
            完整的 Webhook URL
        """
        if self.secret:
            timestamp, sign = self._get_sign()
            return f'{self.webhook_url}&timestamp={timestamp}&sign={sign}'
        return self.webhook_url
    
    def send_text(self, content: str, at_mobiles: Optional[List[str]] = None, at_all: bool = False) -> bool:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            at_mobiles: 需要 @ 的手机号列表
            at_all: 是否 @ 所有人
            
        Returns:
            是否发送成功
        """
        if requests is None:
            print('[钉钉通知] 错误: 未安装 requests 库')
            return False
            
        data = {
            'msgtype': 'text',
            'text': {
                'content': content
            },
            'at': {
                'atMobiles': at_mobiles or [],
                'isAtAll': at_all
            }
        }
        return self._send(data)
    
    def send_markdown(self, title: str, text: str, at_mobiles: Optional[List[str]] = None, at_all: bool = False) -> bool:
        """
        发送 Markdown 消息
        
        Args:
            title: 消息标题（会话列表显示）
            text: Markdown 格式的消息内容
            at_mobiles: 需要 @ 的手机号列表
            at_all: 是否 @ 所有人
            
        Returns:
            是否发送成功
        """
        if requests is None:
            print('[钉钉通知] 错误: 未安装 requests 库')
            return False
            
        data = {
            'msgtype': 'markdown',
            'markdown': {
                'title': title,
                'text': text
            },
            'at': {
                'atMobiles': at_mobiles or [],
                'isAtAll': at_all
            }
        }
        return self._send(data)
    
    def _send(self, data: dict) -> bool:
        """
        发送消息到钉钉
        
        Args:
            data: 消息数据
            
        Returns:
            是否发送成功
        """
        try:
            url = self._get_url()
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            result = response.json()
            
            if result.get('errcode') == 0:
                print('[钉钉通知] 消息发送成功')
                return True
            else:
                print(f'[钉钉通知] 发送失败: {result.get("errmsg", "未知错误")}')
                return False
        except Exception as e:
            print(f'[钉钉通知] 发送异常: {e}')
            return False


def build_checkin_report(results: List[Dict[str, Any]], execution_time: str) -> str:
    """
    构建签到报告 Markdown 内容
    
    Args:
        results: 签到结果列表，每个结果包含:
            - name: 账号名称
            - success: 是否成功
            - message: 结果消息
            - quota_awarded: 本次获得的额度（可选）
            - balance: 当前可用额度（与 used_quota 相加得到账户余额，可选）
            - used_quota: 累计已用额度（可选）
            - usage: 近 30 天用量 {'tokens': int, 'quota': int, 'capped': bool}（可选）
            - checkin_count: 本月签到天数（可选）
            - session_expired: 是否 session 失效（可选）
        execution_time: 执行时间字符串
        
    Returns:
        Markdown 格式的报告内容
    """
    success_list = [r for r in results if r.get('success')]
    fail_list = [r for r in results if not r.get('success')]

    def cell(text) -> str:
        """清理表格单元格内容：去换行、避免竖线打断表格"""
        return str(text).replace('|', '/').replace('\n', ' ').strip()

    def is_expired(r) -> bool:
        message = str(r.get('message', ''))
        return bool(r.get('session_expired') or 'session' in message.lower()
                    or '认证' in message or '过期' in message)

    # 标题
    lines = [
        '# 📋 NewAPI 签到报告',
        '',
        f'**执行时间**: {execution_time}',
        '',
    ]

    notes = []              # 需要补充的长文本（长建议等）
    checkin_parts = []
    has_capped = False

    def lottery_brief(r) -> str:
        """抽奖结果精简：去掉「第N次：」前缀与 emoji，多注用顿号连接"""
        items = []
        for item in r.get('lottery') or []:
            text = cell(item)
            text = re.sub(r'第\s*\d+\s*次\s*[：:]\s*', '', text)
            text = re.sub(r'^[\U0001F000-\U0001FAFF\u2728\u2b50\ufe0f\s]+', '', text)
            if text:
                items.append(text)
        return '、'.join(items) or '-'

    # 表一：签到明细（结果 / 奖励 / 抽奖）
    if results:
        lines.append('| 账号 | 签到结果 | 抽奖 |')
        lines.append('|:--|:--|:--|')

        for r in results:
            name = cell(r.get('name', '未知账号'))

            if r.get('success'):
                quota = r.get('quota_awarded') or 0
                result_str = f'✅ +{format_money(quota)}' if quota else '✅ 已签到'

                checkin_count = r.get('checkin_count')
                if checkin_count:
                    checkin_parts.append(f'{name} {checkin_count} 天')
            else:
                message = cell(r.get('message', ''))
                lower = message.lower()
                if is_expired(r):
                    result_str = '❌ Session 失效，请更新 Cookie'
                elif 'already checked in' in lower or '已签到' in message or '签到过' in message:
                    result_str = '❌ 今日已签到'
                else:
                    result_str = f'❌ {message or "未知错误"}'

                # 短建议并入单元格，长建议放表格下方，避免把表格撑宽
                advice = cell(r['advice']) if r.get('advice') else ''
                if advice and not is_expired(r) and advice not in result_str:
                    if len(advice) <= 12:
                        result_str = f'{result_str}，{advice}'
                    else:
                        notes.append(f'> 💡 {name}：{advice}')

            lines.append(f'| {name} | {result_str} | {lottery_brief(r)} |')

        lines.append('')

    # 表二：站点统计（近 30 天消耗 / 账户余额）
    stat_list = [r for r in results if r.get('balance') is not None or r.get('usage')]
    if stat_list:
        lines.append('| 账号 | 30天消耗 | 账户余额 |')
        lines.append('|:--|:--|:--|')

        for r in stat_list:
            name = cell(r.get('name', '未知账号'))

            usage = r.get('usage')
            if usage:
                cost_str = format_money(usage.get('quota') or 0)
                if usage.get('capped'):
                    cost_str += '*'
                    has_capped = True
            else:
                cost_str = '-'

            balance = r.get('balance')
            balance_str = '-' if balance is None else format_money(
                balance + (r.get('used_quota') or 0)
            )

            lines.append(f'| {name} | {cost_str} | {balance_str} |')

        lines.append('')

    # 表格下方补充信息
    if checkin_parts:
        notes.insert(0, '> 📌 本月已签：' + '、'.join(checkin_parts))
    if has_capped:
        notes.append('> ※ 已达翻页上限，近 30 天数据可能偏少')
    if notes:
        lines.extend(notes)
        lines.append('')

    # 汇总
    total = len(results)
    success_count = len(success_list)
    fail_count = len(fail_list)

    summary = []
    if fail_count == 0:
        summary.append(f'全部成功 ✨ ({success_count}/{total})')
    elif success_count == 0:
        summary.append(f'全部失败 ⚠️ ({fail_count}/{total})')
    else:
        summary.append(f'成功 {success_count}，失败 {fail_count}')

    # 余额合计（有数据的账号）
    balance_results = [r for r in results if r.get('balance') is not None]
    if balance_results:
        total_balance = sum(
            (r.get('balance') or 0) + (r.get('used_quota') or 0) for r in balance_results
        )
        summary.append(f'账户余额合计 {format_money(total_balance)}')

    lines.append('**汇总**: ' + ' · '.join(summary))

    return '\n'.join(lines)


def send_checkin_notification(results: List[Dict[str, Any]], execution_time: Optional[str] = None) -> bool:
    """
    发送签到通知到钉钉
    
    Args:
        results: 签到结果列表
        execution_time: 执行时间（可选，默认使用当前时间）
        
    Returns:
        是否发送成功
    """
    # 从环境变量获取配置
    webhook_url = os.environ.get('DINGTALK_WEBHOOK', '')
    secret = os.environ.get('DINGTALK_SECRET', '')
    
    if not webhook_url:
        print('[钉钉通知] 未配置 DINGTALK_WEBHOOK，跳过通知')
        return False
    
    # 默认执行时间
    if not execution_time:
        execution_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 构建报告
    report = build_checkin_report(results, execution_time)
    
    # 生成标题（用于消息列表预览）
    success_count = len([r for r in results if r.get('success')])
    fail_count = len([r for r in results if not r.get('success')])
    
    if fail_count == 0:
        title = f'✅ 签到成功 ({success_count}个账号)'
    elif success_count == 0:
        title = f'❌ 签到失败 ({fail_count}个账号)'
    else:
        title = f'📋 签到完成 (成功{success_count}/失败{fail_count})'
    
    # 发送通知
    notifier = DingTalkNotifier(webhook_url, secret if secret else None)
    return notifier.send_markdown(title, report)



