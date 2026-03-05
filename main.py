import base64
import json
import logging
import re
import sys
import time
from urllib.parse import urlparse, quote, unquote
import requests

# 默认包含详细的日志记录功能
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 公共订阅转换后端地址 (推测：可能会因高并发而限制，需自行验证其长期可用性)
SUBCONVERTER_API = "https://api.v1.mk/sub"

def read_repositories(file_path="repositories.txt"):
    """读取需要爬取的仓库API或直链"""
    repos = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    repos.append(line)
        logger.info(f"成功读取 {len(repos)} 个订阅源。")
    except Exception as e:
        logger.error(f"读取 repositories.txt 失败: {e}")
    return repos

def extract_raw_urls(repos):
    """如果提供的是 Github API 目录，则展开获取所有文件的 Raw 下载直链"""
    raw_urls = []
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for url in repos:
        if url.startswith("https://api.github.com/"):
            try:
                logger.info(f"正在解析 GitHub 目录结构: {url}")
                res = requests.get(url, headers=headers, timeout=15)
                res.raise_for_status()
                data = res.json()
                if isinstance(data, list):
                    for item in data:
                        name = str(item.get("name", ""))
                        dl_url = item.get("download_url")
                        # 排除图片、程序包等非文本文件
                        if dl_url and not name.endswith(('.png', '.jpg', '.zip', '.exe', '.mp4')):
                            raw_urls.append(dl_url)
            except Exception as e:
                logger.error(f"解析 Github API 失败 {url}: {e}")
        else:
            raw_urls.append(url)
            
    return raw_urls

def fetch_and_convert_nodes(raw_urls):
    """利用外部 API 将各类型订阅还原为基础 URI，并在失败时尝试原生解析"""
    nodes = set()
    
    for url in raw_urls:
        added_count = 0
        encoded_url = quote(url)
        # 强制 target=mixed 以获取按行分割的 URI 明文
        api_url = f"{SUBCONVERTER_API}?target=mixed&url={encoded_url}"
        
        # 路径1：尝试使用公开的订阅转换后端进行还原
        try:
            logger.info(f"尝试外部 API 转换: {url}")
            res = requests.get(api_url, timeout=20)
            res.raise_for_status()
            text = res.text.strip()
            
            # 处理可能的 Base64 嵌套
            try:
                if not "://" in text[:50] and not text.startswith("{"):
                    decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
                    if "://" in decoded:
                        text = decoded
            except Exception:
                pass
                
            for line in text.splitlines():
                line = line.strip()
                if re.match(r'^(ss|vmess|vless|trojan)://', line):
                    nodes.add(line)
                    added_count += 1
                    
        except Exception as e:
            logger.warning(f"外部 API 转换失败 ({url}): {e}。")

        # 路径2 (Fallback)：若外部转换失败或未提取到节点，通过纯文本正则暴力提取
        if added_count == 0:
            logger.info(f"开启回退机制，尝试原生文本提取: {url}")
            try:
                res = requests.get(url, timeout=15)
                text = res.text.strip()
                try:
                    if not "://" in text[:50] and not text.startswith("{"):
                        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
                        if "://" in decoded:
                            text = decoded
                except Exception:
                    pass
                for line in text.splitlines():
                    line = line.strip()
                    if re.match(r'^(ss|vmess|vless|trojan)://', line):
                        nodes.add(line)
            except Exception as e:
                logger.debug(f"原生正则提取同样失败 {url}: {e}")

    logger.info(f"所有链接处理完毕，共提取 {len(nodes)} 个去重 URI。")
    return list(nodes)

def parse_node_details(uri):
    """解析 URI 获取核心参数"""
    host, protocol, network = None, "unknown", "tcp"
    try:
        if uri.startswith('vmess://'):
            protocol = 'vmess'
            b64_str = uri[8:]
            b64_str += '=' * (-len(b64_str) % 4)
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            host = data.get('add')
            network = data.get('net', 'tcp')
        elif uri.startswith(('vless://', 'trojan://', 'ss://')):
            parsed = urlparse(uri)
            protocol = parsed.scheme
            host = parsed.hostname
            if 'type=' in parsed.query:
                match = re.search(r'type=([^&]+)', parsed.query)
                if match:
                    network = match.group(1)
            elif uri.startswith('ss://'):
                match = re.search(r'@([^:]+):(\d+)', uri)
                if match:
                    host = match.group(1)
    except Exception as e:
        pass
    return host, protocol.upper(), network.upper()

def get_geo_info(ip):
    """根据 IP 或域名查询国家代码"""
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3)
        if res.status_code == 200:
            data = res.json()
            return data.get("countryCode", "UN")
    except Exception:
        pass
    return "UN"

def process_and_rename_nodes(nodes):
    """重命名逻辑处理：国家_网络_协议_自增数字"""
    valid_nodes = []
    name_counter = {}
    
    logger.info("开始获取节点归属地并重新命名 (需遵守API速率限制，请耐心等待)...")
    for uri in nodes:
        host, protocol, network = parse_node_details(uri)
        if not host:
            continue
            
        country = get_geo_info(host)
        time.sleep(1.5)  # 严格控制请求频率以防 IP 被封禁
        
        base_name = f"{country}_{network}_{protocol}"
        name_counter[base_name] = name_counter.get(base_name, 0) + 1
        final_name = f"{base_name}_{name_counter[base_name]}"
        
        new_uri = uri
        try:
            if protocol == 'VMESS':
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                data['ps'] = final_name
                new_uri = "vmess://" + base64.b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
            else:
                if '#' in uri:
                    new_uri = uri.split('#')[0] + '#' + final_name
                else:
                    new_uri = uri + '#' + final_name
            valid_nodes.append(new_uri)
            logger.info(f"节点已成功格式化: {final_name}")
        except Exception:
            valid_nodes.append(uri)
            
    return valid_nodes

def main():
    logger.info(">>> 代理节点自动化订阅聚合脚本启动 <<<")
    repos = read_repositories()
    if not repos:
        return
        
    raw_urls = extract_raw_urls(repos)
    raw_nodes = fetch_and_convert_nodes(raw_urls)
    
    if not raw_nodes:
        logger.warning("本次未提取到任何可用节点，任务终止。")
        return
        
    renamed_nodes = process_and_rename_nodes(raw_nodes)
    
    # 将提取并命名后的内容编码为 Base64
    plain_text_sub = "\n".join(renamed_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(">>> 成功封装最新订阅内容至 sub.txt <<<")
    except Exception as e:
        logger.error(f"最终写入文件失败: {e}")

if __name__ == "__main__":
    main()
