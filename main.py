import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
from urllib.parse import urlparse

# 默认配置详细的日志记录功能
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def read_repositories(file_path="repositories.txt"):
    """读取普通的 Github 仓库 URL 列表"""
    repos = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    repos.append(line)
        logger.info(f"成功读取 {len(repos)} 个仓库源地址。")
    except Exception as e:
        logger.error(f"读取 repositories.txt 失败: {e}")
    return repos

def clone_repo(repo_url, target_dir):
    """极速拉取最新仓库文件"""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, target_dir],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"拉取仓库 {repo_url} 失败: {e}")
        return False

def extract_nodes_from_text(text):
    """全协议初步提取，支持全文件 Base64 解码"""
    found_nodes = set()
    try:
        if not "://" in text[:50] and not text.startswith("{"):
            decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
            if "://" in decoded:
                text += "\n" + decoded
    except Exception:
        pass

    lines = text.splitlines()
    regex_pattern = re.compile(r'(?i)(ss|ssr|vmess|vless|trojan|tuic|hysteria2?|hy2|wg|wireguard|socks5?)://[^\s"' + r"'<>]+")
    
    for line in lines:
        line = line.strip()
        match = regex_pattern.search(line)
        if match:
            found_nodes.add(match.group(0))
            
    return found_nodes

def process_local_directory(base_dir):
    """遍历提取文件内容"""
    all_nodes = set()
    for root, _, files in os.walk(base_dir):
        if '.git' in root:
            continue
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.zip', '.exe', '.mp4', '.pdf')):
                continue
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                nodes = extract_nodes_from_text(content)
                if nodes:
                    all_nodes.update(nodes)
            except Exception as e:
                logger.debug(f"读取文件 {file_path} 失败: {e}")
    return all_nodes

def is_valid_uuid(val):
    """严格校验 UUID 格式"""
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False

def validate_and_format_uri(uri):
    """
    深度清洗与格式化：强制修复 JSON 类型错误，拦截残缺的 SSR，去除尾部残留垃圾。
    一旦发现会引发 Go 客户端崩溃的严重残缺，直接返回 None 丢弃。
    """
    try:
        uri = uri.strip()
        # 移除 Markdown 或中文括号等抓取时连带的尾部污染
        uri = re.split(r'[`【】\s]', uri)[0].strip()
        if len(uri) < 15:
            return None

        uri_lower = uri.lower()

        if uri_lower.startswith('vmess://'):
            b64_str = uri[8:]
            b64_str = b64_str.split('#')[0]
            # 仅允许合法 Base64 字符
            b64_str = re.sub(r'[^a-zA-Z0-9\+\/\=\-_]', '', b64_str)
            b64_str += '=' * (-len(b64_str) % 4)
            
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            
            # 缺失核心参数的残缺配置直接抛弃
            if not all(k in data for k in ('add', 'port', 'id')):
                return None
            if not data['add'] or not str(data['port']).isdigit() or not data['id']:
                return None

            # 核心修复：强制将数字类型的 'v' 转换为 Go 结构体要求的 String 类型
            # 强制将端口统一转为 Integer 类型以匹配主流客户端格式
            data['v'] = "2"
            data['port'] = int(data['port'])
            
            # 剔除可能造成干扰的非法字段
            data.pop('test_name', None)

            clean_b64 = base64.b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
            return f"vmess://{clean_b64}"

        elif uri_lower.startswith('ssr://'):
            b64_str = uri[6:]
            b64_str = b64_str.split('#')[0]
            b64_str = re.sub(r'[^a-zA-Z0-9\-\_\+\/\=]', '', b64_str)
            b64_str += '=' * (-len(b64_str) % 4)
            
            decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
            parts = decoded.split(':')
            
            # 拦截导致 Panic 的罪魁祸首：缺少端口或无法分割的 SSR 链接
            if len(parts) < 6 or not parts[1].isdigit():
                return None
            return uri

        elif uri_lower.startswith(('vless://', 'trojan://')):
            parsed = urlparse(uri)
            if not parsed.hostname or not parsed.port or not parsed.username:
                return None
            # VLESS 的 username 必须是标准 UUID，踢掉所有混进来的 Telegram 广告账号
            if uri_lower.startswith('vless://') and not is_valid_uuid(parsed.username):
                return None
            return uri

        elif uri_lower.startswith('ss://'):
            parsed = urlparse(uri)
            if not parsed.hostname:
                return None
            return uri

        # Tuic, Hysteria, WG 等其他协议的底线检测
        parsed = urlparse(uri)
        if not parsed.hostname:
            return None
        return uri

    except Exception:
        # 遇到任何解析报错，绝不保留，直接丢弃
        return None

def clean_and_deduplicate(nodes):
    """执行最终的深度验证与去重拦截"""
    unique_map = {}
    for uri in nodes:
        clean_uri = validate_and_format_uri(uri)
        if not clean_uri:
            continue
            
        try:
            uri_lower = clean_uri.lower()
            if uri_lower.startswith('vmess://'):
                b64_str = clean_uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                
                core_data = data.copy()
                core_data.pop('ps', None)
                core_id = "vmess://" + json.dumps(core_data, sort_keys=True)
                
                if core_id not in unique_map:
                    unique_map[core_id] = clean_uri
            elif uri_lower.startswith('ssr://'):
                if clean_uri not in unique_map:
                    unique_map[clean_uri] = clean_uri
            else:
                core_id = clean_uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = clean_uri
        except Exception:
            continue
            
    logger.info(f"提取总原始数据: {len(nodes)}，严格拦截质检后保留可用节点: {len(unique_map)}")
    return list(unique_map.values())

def main():
    logger.info(">>> 极速纯净版：代理自动化全量收集脚本启动 (含防崩溃协议质检) <<<")
    repos = read_repositories()
    if not repos:
        return
        
    temp_workspace = "temp_repos"
    if not os.path.exists(temp_workspace):
        os.makedirs(temp_workspace)
        
    raw_nodes = set()
    
    for i, repo in enumerate(repos):
        repo_dir = os.path.join(temp_workspace, f"repo_{i}")
        logger.info(f"正在拉取: {repo}")
        if clone_repo(repo, repo_dir):
            nodes_found = process_local_directory(repo_dir)
            raw_nodes.update(nodes_found)
            
    if not raw_nodes:
        logger.warning("本次未提取到任何数据。")
        shutil.rmtree(temp_workspace, ignore_errors=True)
        return
        
    final_nodes = clean_and_deduplicate(list(raw_nodes))
    
    plain_text_sub = "\n".join(final_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(f">>> 成功将 {len(final_nodes)} 个合格节点封装至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    shutil.rmtree(temp_workspace, ignore_errors=True)

if __name__ == "__main__":
    main()
