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
    # 基础正则匹配
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
    """严格校验 UUID 格式，防止广告文本导致客户端崩溃"""
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False

def clean_and_deduplicate(nodes):
    """
    严格清洗与去重：剥离损坏数据，拒绝非法格式，仅保留高质量原汁原味的 URI。
    """
    unique_map = {}
    for uri in nodes:
        try:
            # 过滤明显被截断或破损的极短垃圾数据
            if len(uri) < 15:
                continue

            uri_lower = uri.lower()
            
            if uri_lower.startswith('vmess://'):
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                try:
                    data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                except Exception:
                    continue # JSON 解析失败，直接判定为垃圾数据抛弃
                
                # 校验核心字段，缺失则直接抛弃
                if 'add' not in data or 'port' not in data or not data['add']:
                    continue
                    
                core_data = data.copy()
                core_data.pop('ps', None)
                core_id = "vmess://" + json.dumps(core_data, sort_keys=True)
                
                if core_id not in unique_map:
                    unique_map[core_id] = uri

            elif uri_lower.startswith('vless://'):
                parsed = urlparse(uri)
                # VLESS 必须严格包含 username(UUID), hostname 和 port
                if not parsed.hostname or not parsed.port or not parsed.username:
                    continue
                    
                # 严格要求 VLESS 必须为标准 UUID，剔除混入的 Telegram 广告账号
                if not is_valid_uuid(parsed.username):
                    continue
                    
                core_id = uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = uri
                    
            elif uri_lower.startswith('trojan://'):
                parsed = urlparse(uri)
                if not parsed.hostname or not parsed.port or not parsed.username:
                    continue
                core_id = uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = uri

            elif uri_lower.startswith('ssr://'):
                if uri not in unique_map:
                    unique_map[uri] = uri

            else:
                # ss, tuic, hysteria 等其他协议，通过 urlparse 基础有效性验证
                parsed = urlparse(uri)
                if not parsed.hostname:
                    continue
                core_id = uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = uri
                    
        except Exception:
            # 【关键修复】：一旦解析过程中出现任何异常数组越界或报错，绝不手软，直接丢弃该数据！
            continue
            
    logger.info(f"提取总原始数据数: {len(nodes)}，严格质检与去重后保留可用节点: {len(unique_map)}")
    return list(unique_map.values())

def main():
    logger.info(">>> 极速纯净版：代理自动化全量收集脚本启动 (含严格防崩溃质检) <<<")
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
        
    # 清洗和强力去重，剔除所有可能引发崩溃的毒药数据
    final_nodes = clean_and_deduplicate(list(raw_nodes))
    
    # Base64 重新封装
    plain_text_sub = "\n".join(final_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(f">>> 成功将 {len(final_nodes)} 个可用节点封装至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    # 清理临时文件
    shutil.rmtree(temp_workspace, ignore_errors=True)

if __name__ == "__main__":
    main()
