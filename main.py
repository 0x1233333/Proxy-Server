import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
import socket
import concurrent.futures
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
    严格清洗与格式化，拦截所有能引发核心崩溃的残缺链接。
    """
    try:
        uri = uri.strip()
        uri = re.split(r'[`【】\s]', uri)[0].strip()
        if len(uri) < 15:
            return None

        uri_lower = uri.lower()

        if uri_lower.startswith('vmess://'):
            b64_str = uri[8:]
            b64_str = b64_str.split('#')[0]
            b64_str = re.sub(r'[^a-zA-Z0-9\+\/\=\-_]', '', b64_str)
            b64_str += '=' * (-len(b64_str) % 4)
            
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            
            if not all(k in data for k in ('add', 'port', 'id')):
                return None
            if not data['add'] or not str(data['port']).isdigit():
                return None
            if not is_valid_uuid(data['id']):
                return None

            port_int = int(data['port'])
            if not (1 <= port_int <= 65535):
                return None

            data['v'] = "2"
            data['port'] = port_int
            data.pop('test_name', None)
            data.pop('ps', None)

            clean_b64 = base64.b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
            return f"vmess://{clean_b64}"

        elif uri_lower.startswith('ssr://'):
            b64_str = uri[6:]
            b64_str = b64_str.split('#')[0]
            b64_str = re.sub(r'[^a-zA-Z0-9\-\_\+\/\=]', '', b64_str)
            b64_str += '=' * (-len(b64_str) % 4)
            
            decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
            parts = decoded.split(':')
            
            if len(parts) < 6 or not parts[1].isdigit():
                return None
            port_int = int(parts[1])
            if not (1 <= port_int <= 65535):
                return None
            return uri

        elif uri_lower.startswith(('vless://', 'trojan://')):
            parsed = urlparse(uri)
            if not parsed.hostname or not parsed.port or not parsed.username:
                return None
            if uri_lower.startswith('vless://') and not is_valid_uuid(parsed.username):
                return None
            return uri

        elif uri_lower.startswith('ss://'):
            parsed = urlparse(uri)
            if not parsed.hostname:
                return None
            return uri

        parsed = urlparse(uri)
        if not parsed.hostname:
            return None
        return uri

    except Exception:
        return None

def get_host_and_port(uri):
    """从清洗后的标准 URI 中提取 Host 和 Port 用于 TCP 测活"""
    try:
        uri_lower = uri.lower()
        if uri_lower.startswith('vmess://'):
            b64_str = uri[8:]
            b64_str += '=' * (-len(b64_str) % 4)
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            return data.get('add'), int(data.get('port'))
            
        elif uri_lower.startswith('ssr://'):
            b64_str = uri[6:].split('#')[0]
            b64_str += '=' * (-len(b64_str) % 4)
            decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
            parts = decoded.split(':')
            return parts[0], int(parts[1])
            
        else:
            parsed = urlparse(uri)
            host = parsed.hostname
            port = parsed.port
            # 兼容处理 IPv6 格式的中括号剥离，socket 连接时不需要外层括号
            if host:
                host = host.strip('[]')
            if not host and '@' in uri:
                match = re.search(r'@([^:]+):(\d+)', uri)
                if match:
                    return match.group(1).strip('[]'), int(match.group(2))
            return host, port
    except Exception:
        return None, None

def check_node_alive(uri, timeout=2.0):
    """TCP Socket 基础连通性测试"""
    host, port = get_host_and_port(uri)
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False

def filter_alive_nodes(nodes, max_workers=100):
    """百线程并发测活，抛弃物理断连的死节点"""
    alive_nodes = []
    total = len(nodes)
    logger.info(f"开启 {max_workers} 线程进行 TCP 并发测活，待测节点共计 {total} 个，请耐心等待...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_uri = {executor.submit(check_node_alive, uri): uri for uri in nodes}
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_uri):
            uri = future_to_uri[future]
            done_count += 1
            
            # 每测试完 2000 个节点打印一次进度，防止撑爆 GitHub Actions 日志限制
            if done_count % 2000 == 0 or done_count == total:
                logger.info(f"测活进度: {done_count} / {total} (当前存活: {len(alive_nodes)})")
                
            try:
                if future.result():
                    alive_nodes.append(uri)
            except Exception:
                pass
                
    logger.info(f"测活彻底完成！剔除死节点后，最终保留存活节点数: {len(alive_nodes)}")
    return alive_nodes

def clean_and_deduplicate(nodes):
    """严格拦截质检与核心去重"""
    unique_map = {}
    for uri in nodes:
        clean_uri = validate_and_format_uri(uri)
        if not clean_uri:
            continue
        try:
            uri_lower = clean_uri.lower()
            if uri_lower.startswith('vmess://') or uri_lower.startswith('ssr://'):
                if clean_uri not in unique_map:
                    unique_map[clean_uri] = clean_uri
            else:
                core_id = clean_uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = clean_uri
        except Exception:
            continue
            
    logger.info(f"原始数据总量: {len(nodes)}，严格过滤与去重后初步合格节点: {len(unique_map)}")
    return list(unique_map.values())

def main():
    logger.info(">>> 极速纯净版：代理自动化收集 (含铁血质检 + TCP 并发测活) <<<")
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
        
    # 第一步：清洗、格式纠正和防重复
    formatted_nodes = clean_and_deduplicate(list(raw_nodes))
    
    # 第二步：多线程并发物理测活
    final_alive_nodes = filter_alive_nodes(formatted_nodes)
    
    # 第三步：Base64 重新封装
    plain_text_sub = "\n".join(final_alive_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(f">>> 成功将 {len(final_alive_nodes)} 个高纯度且物理连通的节点封装至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    shutil.rmtree(temp_workspace, ignore_errors=True)

if __name__ == "__main__":
    main()
