import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys

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
    """
    强力去重：仅对比核心配置，保留原汁原味的 URI。
    即使两个节点名字不同，只要底层 IP 和端口配置一样，也会被当做重复项剔除。
    """
    unique_map = {}
    for uri in nodes:
        try:
            uri_lower = uri.lower()
            if uri_lower.startswith('vmess://'):
                b64_str = uri[8:]
                b64_str += '=' * (-len(b64_str) % 4)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                
                # 复制一份核心数据用于生成唯一特征码，忽略原本的名字(ps)
                core_data = data.copy()
                core_data.pop('ps', None)
                core_id = "vmess://" + json.dumps(core_data, sort_keys=True)
                
                if core_id not in unique_map:
                    unique_map[core_id] = uri
            elif uri_lower.startswith('ssr://'):
                if uri not in unique_map:
                    unique_map[uri] = uri
            else:
                # vless, trojan 等截断 # 后的备注内容作为唯一特征码
                core_id = uri.split('#')[0]
                if core_id not in unique_map:
                    unique_map[core_id] = uri
        except Exception:
            # 解析失败的节点保守保留
            if uri not in unique_map:
                unique_map[uri] = uri
            
    logger.info(f"提取总节点数: {len(nodes)}，核心去重后保留: {len(unique_map)}")
    return list(unique_map.values())

def main():
    logger.info(">>> 极速纯净版：代理自动化全量收集脚本启动 <<<")
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
        
    # 清洗和强力去重，直接获取保留原名的节点列表
    final_nodes = clean_and_deduplicate(list(raw_nodes))
    
    # Base64 重新封装
    plain_text_sub = "\n".join(final_nodes)
    encoded_sub = base64.b64encode(plain_text_sub.encode('utf-8')).decode('utf-8')
    
    try:
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded_sub)
        logger.info(">>> 成功封装全部订阅内容至 sub.txt <<<")
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        
    # 清理临时文件
    shutil.rmtree(temp_workspace, ignore_errors=True)

if __name__ == "__main__":
    main()
