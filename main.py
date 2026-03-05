import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
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
    """使用 git clone --depth 1 拉取仓库最新文件，避免拉取庞大的历史记录"""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    try:
        logger.info(f"正在拉取仓库: {repo_url}")
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, target_dir],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"拉取仓库 {repo_url} 失败: {e}")
        return False

def extract_nodes_from_text(text):
    """从纯文本(包括MD文件)中提取代理节点，支持 Mihomo 和 Sing-box 全协议，支持 Base64 自动解密"""
    found_nodes = set()
    
    # 尝试将整体视为 Base64 解码 (应对全文件 Base64 的情况)
    try:
        if not "://" in text[:50] and not text.startswith("{"):
            decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
            if "://" in decoded:
                text += "\n" + decoded
    except Exception:
        pass

    # 提取节点特征的正则：支持 ss/ssr/vmess/vless/trojan/tuic/hysteria/hy2/wg/wireguard/socks
    # 忽略大小写，遇到空格或特殊括号截断
    lines = text.splitlines()
    regex_pattern = re.compile(r'(?i)(ss|ssr|vmess|vless|trojan|tuic|hysteria2?|hy2|wg|wireguard|socks5?)://[^\s"' + r"'<>]+")
    
    for line in lines:
        line = line.strip()
        match = regex_pattern.search(line)
        if match:
            found_nodes.add(match.group(0))
            
    return found_nodes

def process_local_directory(base_dir):
    """遍历本地目录中的所有文件并提取节点"""
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

def clean_and_deduplicate(nodes):
    """强力去重：剥离原有备注信息，仅比较核心配置数据，兼容全协议"""
    unique_map = {}
    
    for uri in nodes:
        try:
            uri_lower = uri.lower()
            if uri_lower.startswith('vmess://'):
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                data.pop('ps', None)
                core_id = "vmess://" + json.dumps(data, sort_keys=True)
                unique_map[core_id] = uri
            elif uri_lower.startswith('ssr://'):
                # SSR 结构特殊，采用原链直接去重
                unique_map[uri] = uri
            else:
                # 其他协议 (vless, trojan, tuic, hy2 等) 剥离 # 号后的备注
                core_id = uri.split('#')[0]
                unique_map[core_id] = uri
        except Exception:
            # 解析失败的节点保留原样
            unique_map[uri] = uri
            
    logger.info(f"去重前节点数: {len(nodes)}，强力去重后剩余: {len(unique_map)}")
    return list(unique_map.values())

def parse_node_details(uri):
    """提取节点的 Host 和协议信息用于归属地查询，兼容新协议"""
    host, protocol, network = None, "unknown", "tcp"
    try:
        uri_lower = uri.lower()
        if uri_lower.startswith('vmess://'):
            protocol = 'vmess'
            b64_str = uri[8:]
            b64_str += '=' * (-len(b64_str) % 4)
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            host = data.get('add') or data.get('host')
            network = data.get('net', 'tcp')
        elif uri_lower.startswith('ssr://'):
            protocol = 'ssr'
            # 尝试浅层解析 SSR 拿到 Host，失败则放弃并依靠默认值
            b64_str = uri[6:]
            b64_str += '=' * (-len(b64_str) % 4)
            decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
            host = decoded.split(':')[0]
        else:
            # 兼容 vless, trojan, tuic, hy2, wg, socks 等标准 URI 结构
            parsed = urlparse(uri)
            protocol = parsed.scheme.lower()
            host = parsed.hostname
            if 'type=' in parsed.query:
                match = re.search(r'type=([^&]+)', parsed.query)
                if match:
                    network = match.group(1)
            elif protocol == 'ss':
                match = re.search(r'@([^:]+):(\d+)', uri)
                if match:
                    host = match.group(1)
    except Exception:
        pass
        
    return host, protocol.upper(), network.upper()

def get_geo_info(ip):
    """查询 IP 归属地"""
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3)
        if res.status_code == 200:
            data = res.json()
            return data.get("countryCode", "UN")
    except Exception:
        pass
    return "UN"

def process_and_rename_nodes(nodes):
    """节点重命名: 国家_网络_协议_序号"""
    valid_nodes = []
    name_counter = {}
    
    logger.info("开始获取节点归属地并重新命名 (需遵守API防DDoS速率限制，稍等片刻)...")
    for uri in nodes:
        host, protocol, network = parse_node_details(uri)
        
        # 即使无法解析 Host（如特殊混淆格式），也不丢弃节点，直接标记为 UN
        if not host:
            country = "UN"
        else:
            country = get_geo_info(host)
            time.sleep(1.5)  # 严格限制并发速率，防止 ip-api 封禁
            
        base_name = f"{country}_{network}_{protocol}"
        name_counter[base_name] = name_counter.get(base_name, 0) + 1
        final_name = f"{base_name}_{name_counter[base_name]}"
        
        try:
            if protocol == 'VMESS':
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                data['ps'] = final_name
                new_uri = "vmess://" + base64.b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
            else:
                # SSR 及其他标准格式统一通过追加 / 替换 # 号进行重命名
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
    logger.info(">>> 本地 Git 模式全协议代理提取脚本启动 <<<")
    repos = read_repositories()
    if not repos:
        return
        
    temp_workspace = "temp_repos"
    if not os.path.exists(temp_workspace):
        os.makedirs(temp_workspace)
        
    raw_nodes = set()
    
    for i, repo in enumerate(repos):
        repo_dir = os.path.join(temp_workspace, f"repo_{i}")
        if clone_repo(repo, repo_dir):
            nodes_found = process_local_directory(repo_dir)
            raw_nodes.update(nodes_found)
            logger.info(f"从仓库 {repo} 累计提取到 {len(nodes_found)} 个节点")
            
    if not raw_nodes:
        logger.warning("本次未提取到任何可用节点。")
        shutil.rmtree(temp_workspace)
        return
        
    # 清洗和强力去重
    unique_nodes = clean_and_deduplicate(list(raw_nodes))
    
    # 归属地获取与重命名
    renamed_nodes = process_and_rename_nodes(unique_nodes)
    
    # Base64 重新封装
    plain_text_sub = "\n".join(renamed_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(">>> 成功封装全协议订阅内容至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    # 清理临时文件
    try:
        shutil.rmtree(temp_workspace)
        logger.info("临时仓库目录清理完毕。")
    except Exception as e:
        logger.debug(f"清理临时目录失败: {e}")

if __name__ == "__main__":
    main()
