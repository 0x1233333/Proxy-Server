import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
import requests

# 默认配置详细的日志记录功能
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 基础搜索关键词池
KEYWORDS = [
    "免费节点", "v2ray free", "clash free", "singbox free", 
    "vless trojan 节点", "free proxies", "科学上网 节点", "翻墙 订阅"
]

def load_list(filename):
    """加载文本列表（白名单或黑名单）"""
    items = set()
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    items.add(line)
    return items

def save_list(filename, items):
    """保存文本列表"""
    with open(filename, 'w', encoding='utf-8') as f:
        for item in sorted(list(items)):
            f.write(f"{item}\n")

def load_stats(filename="keyword_stats.json"):
    """加载关键词统计数据"""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {kw: {"tested": 0, "success": 0} for kw in KEYWORDS}

def save_stats(stats, filename="keyword_stats.json"):
    """保存关键词统计数据"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=4)

def test_repo_for_nodes(repo_url, target_dir):
    """克隆并使用正则浅层测试该仓库是否真包含代理节点"""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
        
    try:
        # 极速拉取，不拉历史记录
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, target_dir],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        )
    except Exception as e:
        logger.debug(f"克隆 {repo_url} 失败或超时: {e}")
        return False

    regex_pattern = re.compile(r'(?i)(ss|ssr|vmess|vless|trojan|tuic|hysteria2?|hy2|wg|wireguard|socks5?)://[^\s"' + r"'<>]+")
    found_any = False
    
    # 快速遍历本地文件
    for root, _, files in os.walk(target_dir):
        if '.git' in root:
            continue
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.zip', '.exe')):
                continue
            try:
                with open(os.path.join(root, file), 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                # Base64 解码尝试
                try:
                    if not "://" in content[:50] and not content.startswith("{"):
                        decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                        if "://" in decoded:
                            content += "\n" + decoded
                except Exception:
                    pass
                    
                if regex_pattern.search(content):
                    found_any = True
                    break
            except Exception:
                pass
        if found_any:
            break
            
    # 清理临时目录
    shutil.rmtree(target_dir, ignore_errors=True)
    return found_any

def search_github_repos(keyword, days_ago=7):
    """利用 Github API 搜索近期活跃的仓库"""
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
        
    # 只搜索最近 N 天内有更新的仓库
    date_threshold = (datetime.utcnow() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
    query = f"{keyword} pushed:>{date_threshold} fork:true"
    url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=15"
    
    try:
        logger.info(f"正在搜索关键词: [{keyword}]")
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        items = res.json().get("items", [])
        return [item["html_url"] for item in items]
    except Exception as e:
        logger.error(f"GitHub API 搜索失败 [{keyword}]: {e}")
        return []

def main():
    logger.info(">>> 自动化资源库寻猎与统计脚本启动 <<<")
    
    repo_file = "repositories.txt"
    black_file = "blacklist.txt"
    stats_file = "keyword_stats.json"
    
    # 建立空的黑名单文件（如果不存在）
    if not os.path.exists(black_file):
        open(black_file, 'w').close()
        
    whitelist = load_list(repo_file)
    blacklist = load_list(black_file)
    stats = load_stats(stats_file)
    
    temp_dir = "temp_discover"
    new_found_count = 0
    
    # 同步 stats 里的关键词，以防代码更新新增了关键词
    for kw in KEYWORDS:
        if kw not in stats:
            stats[kw] = {"tested": 0, "success": 0}
            
    for keyword in KEYWORDS:
        urls = search_github_repos(keyword, days_ago=14) # 扩大到14天内活跃的
        time.sleep(3) # 防止触发 API 速率限制
        
        for url in urls:
            if url in whitelist or url in blacklist:
                continue
                
            logger.info(f"发现新仓库，开始测试: {url}")
            stats[keyword]["tested"] += 1
            
            is_valid = test_repo_for_nodes(url, temp_dir)
            if is_valid:
                logger.info(f"✅ 测试成功，存在节点！加入白名单: {url}")
                whitelist.add(url)
                stats[keyword]["success"] += 1
                new_found_count += 1
            else:
                logger.info(f"❌ 测试失败，无节点或无法访问。加入黑名单: {url}")
                blacklist.add(url)
                
    # 保存结果
    save_list(repo_file, whitelist)
    save_list(black_file, blacklist)
    save_stats(stats, stats_file)
    
    logger.info(f">>> 寻猎结束！本次共挖掘并新增 {new_found_count} 个有效源仓库 <<<")

if __name__ == "__main__":
    main()
