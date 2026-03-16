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
    """全协议提取节点，支持 Base64 解码"""
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

def clean_and_deduplicate(nodes):
    """提取节点的 Core ID 用于映射比对，返回 {core_id: uri} 字典"""
    unique_map = {}
    for uri in nodes:
        try:
            uri_lower = uri.lower()
            if uri_lower.startswith('vmess://'):
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                data.pop('ps', None) # 彻底抛弃旧名字
                core_id = "vmess://" + json.dumps(data, sort_keys=True)
                unique_map[core_id] = uri
            elif uri_lower.startswith('ssr://'):
                unique_map[uri] = uri
            else:
                # vless, trojan 等截断 # 后的内容作为唯一标识
                core_id = uri.split('#')[0]
                unique_map[core_id] = uri
        except Exception:
            unique_map[uri] = uri
            
    logger.info(f"去重前节点数: {len(nodes)}，强力去重后剩余: {len(unique_map)}")
    return unique_map

def parse_node_details(uri):
    """提取节点的 Host 和协议信息用于归属地查询"""
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
            b64_str = uri[6:]
            b64_str += '=' * (-len(b64_str) % 4)
            decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
            host = decoded.split(':')[0]
        else:
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

def inject_name(uri, final_name):
    """将最终名称安全地注入回节点 URI"""
    try:
        uri_lower = uri.lower()
        if uri_lower.startswith('vmess://'):
            b64_str = uri[8:]
            b64_str += '=' * (-len(b64_str) % 4)
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            data['ps'] = final_name
            return "vmess://" + base64.b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
        else:
            if '#' in uri:
                return uri.split('#')[0] + '#' + final_name
            else:
                return uri + '#' + final_name
    except Exception:
        return uri

def process_and_rename_nodes(core_map):
    """状态对比：复用老节点名称，新增测速，自动抛弃已删除的节点"""
    mapping_file = "node_mapping.json"
    old_mapping = {}
    if os.path.exists(mapping_file):
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                old_mapping = json.load(f)
        except Exception:
            pass

    new_mapping = {}
    valid_nodes = []
    name_counter = {} # 记录每个国家协议的最高序号，防止新增时重名

    new_core_ids = []

    # 第一阶段：比对历史留存节点
    for core_id, uri in core_map.items():
        if core_id in old_mapping:
            # 节点仍然存在，直接复用历史命名
            final_name = old_mapping[core_id]
            new_mapping[core_id] = final_name
            
            # 更新序号计数器 (例如从 US_TCP_VLESS_5 中提取 5)
            match = re.match(r'(.+)_(\d+)$', final_name)
            if match:
                base_name = match.group(1)
                idx = int(match.group(2))
                if name_counter.get(base_name, 0) < idx:
                    name_counter[base_name] = idx
                    
            valid_nodes.append(inject_name(uri, final_name))
        else:
            # 发现新节点，送入第二阶段处理
            new_core_ids.append((core_id, uri))

    logger.info(f"历史节点匹配成功并保留: {len(valid_nodes)} 个。")

    # 第二阶段：处理并命名全新的节点
    if new_core_ids:
        logger.info(f"检测到 {len(new_core_ids)} 个新增节点，正在进行增量归属地查询...")
    else:
        logger.info("无新增节点，跳过网络请求。")

    for core_id, uri in new_core_ids:
        host, protocol, network = parse_node_details(uri)
        if not host:
            country = "UN"
        else:
            country = get_geo_info(host)
            time.sleep(1.5)  # 限速保护
            
        base_name = f"{country}_{network}_{protocol}"
        name_counter[base_name] = name_counter.get(base_name, 0) + 1
        final_name = f"{base_name}_{name_counter[base_name]}"
        
        new_mapping[core_id] = final_name
        valid_nodes.append(inject_name(uri, final_name))
        logger.info(f"新增节点已分配: {final_name}")

    # 保存全新的映射表 (上游删掉的节点因为没出现在 core_map 里，自然就被清除了)
    try:
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(new_mapping, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"保存节点状态映射失败: {e}")

    return valid_nodes

def main():
    logger.info(">>> 状态对比增量更新版：代理自动化提取脚本启动 <<<")
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
        logger.warning("本次未提取到任何可用节点。")
        shutil.rmtree(temp_workspace, ignore_errors=True)
        return
        
    # 清洗和强力去重，返回核心配置映射字典
    core_map = clean_and_deduplicate(list(raw_nodes))
    
    # 执行增量重命名逻辑
    renamed_nodes = process_and_rename_nodes(core_map)
    
    # Base64 重新封装
    plain_text_sub = "\n".join(renamed_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(">>> 成功封装增量订阅内容至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    # 清理临时文件
    shutil.rmtree(temp_workspace, ignore_errors=True)

if __name__ == "__main__":
    main()
