"""
配置加载模块 - 智能管理多电脑环境配置 + AKO 统一配置中心
支持配置文件和环境变量两种方式
"""
import os
import json
import sys
from typing import Dict, Any

# ── AKO 统一配置中心 ─────────────────────────────────────────
try:
    sys.path.insert(0, "D:/AKO_Hub")
    from core.ako_config import get_config as get_ako_config
    _ako_cfg = get_ako_config()
except Exception:
    _ako_cfg = None


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_file: str = None):
        """
        初始化配置加载器
        
        Args:
            config_file: 配置文件路径,默认为当前目录下的 config.json
        """
        if config_file is None:
            self.config_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 
                "config.json"
            )
        else:
            self.config_file = config_file
        
        self.config = self._load_config()
        self.active_profile = self._get_active_profile()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"配置文件不存在: {self.config_file}\n"
                f"请从 config.example.json 复制并修改"
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
    
    def _get_active_profile(self) -> str:
        """获取当前激活的配置项(支持环境变量覆盖)"""
        # 优先使用环境变量
        env_profile = os.getenv('AKO_PROFILE')
        if env_profile:
            return env_profile
        
        # 否则使用配置文件中的设置
        return self.config.get('active_profile', 'computer_a')
    
    @property
    def db_path(self) -> str:
        """获取数据库路径"""
        profile = self._get_current_profile()
        db_path = profile.get('db_path', '.')
        
        # 如果是相对路径或 '.', 转换为绝对路径
        if db_path == '.' or db_path == '':
            # '.' 或空字符串表示脚本所在目录
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = base_dir
        elif not os.path.isabs(db_path):
            # 其他相对路径,拼接到脚本目录
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, db_path)
        
        return db_path
    
    @property
    def pdf_folder(self) -> str:
        """获取 PDF 文件夹路径"""
        profile = self._get_current_profile()
        return profile.get('pdf_folder', '')
    
    @property
    def word_folder(self) -> str:
        """获取 Word 文件夹路径"""
        profile = self._get_current_profile()
        return profile.get('word_folder', '')
    
    @property
    def ppt_folder(self) -> str:
        """获取 PPT 文件夹路径"""
        profile = self._get_current_profile()
        return profile.get('ppt_folder', '')
    
    @property
    def img_folder(self) -> str:
        """获取图片文件夹路径"""
        profile = self._get_current_profile()
        return profile.get('img_folder', '')
    
    @property
    def collection_name(self) -> str:
        """获取集合名称"""
        profile = self._get_current_profile()
        return profile.get('collection_name', 'ako_photos')
    
    @property
    def chunk_size(self) -> int:
        """获取分块大小"""
        common = self.config.get('common_settings', {})
        return common.get('chunk_size', 768)
    
    @property
    def overlap(self) -> int:
        """获取重叠大小"""
        common = self.config.get('common_settings', {})
        return common.get('overlap', 256)
    
    @property
    def batch_size(self) -> int:
        """获取批量大小"""
        common = self.config.get('common_settings', {})
        return common.get('batch_size', 16)
    
    @property
    def embedding_model(self) -> str:
        """获取嵌入模型名称"""
        common = self.config.get('common_settings', {})
        return common.get('embedding_model', 'bge-m3')
    
    @property
    def ocr_languages(self) -> str:
        """获取 OCR 语言设置"""
        common = self.config.get('common_settings', {})
        return common.get('ocr_languages', 'chi_sim+eng')
    
    @property
    def chroma_mode(self) -> str:
        """获取 ChromaDB 连接模式: 'local' 或 'remote'"""
        common = self.config.get('common_settings', {})
        return common.get('chroma_mode', 'local')
    
    @property
    def chroma_server_host(self) -> str:
        """获取 ChromaDB 服务器地址"""
        common = self.config.get('common_settings', {})
        return common.get('chroma_server_host', 'localhost')
    
    @property
    def chroma_server_port(self) -> int:
        """获取 ChromaDB 服务器端口"""
        common = self.config.get('common_settings', {})
        return common.get('chroma_server_port', 8000)

    @property
    def confidence_threshold(self) -> float:
        """获取查询置信度阈值"""
        qs = self.config.get('query_settings', {})
        return qs.get('confidence_threshold', 0.3)

    @property
    def similarity_threshold(self) -> float:
        """获取相似度阈值"""
        qs = self.config.get('query_settings', {})
        return qs.get('similarity_threshold', 0.55)

    @property
    def llm_api_base(self) -> str:
        """获取 LLM API 基础 URL"""
        llm = self.config.get('llm_settings', {})
        return llm.get('api_base', 'https://api.deepseek.com')

    @property
    def llm_api_key(self) -> str:
        """获取 LLM API Key — 优先环境变量，回退 config.json"""
        key = os.getenv("AKO_KNOWLEDGE_DEEPSEEK_API_KEY", "")
        if key:
            return key
        llm = self.config.get('llm_settings', {})
        return llm.get('api_key', '')

    # ── Hub 集成属性（优先 ako_config，回退 config.json）────────

    @property
    def hub_enabled(self) -> bool:
        """Hub 双写是否启用"""
        hub_cfg = self.config.get('hub_integration', {})
        return hub_cfg.get('enabled', False)

    @property
    def hub_chroma_root(self) -> str:
        """Hub ChromaDB 根目录"""
        if _ako_cfg and _ako_cfg.chroma_root:
            return _ako_cfg.chroma_root
        hub_cfg = self.config.get('hub_integration', {})
        return hub_cfg.get('hub_chroma_root', '')

    @property
    def hub_collection(self) -> str:
        """Hub 目标 collection 名称"""
        # 从当前 profile 读取
        profile = self._get_current_profile()
        return profile.get('hub_collection', 'ako_taoli_general_arch')

    @property
    def hub_meta_db(self) -> str:
        """Hub 元数据库路径"""
        if _ako_cfg and _ako_cfg.meta_db:
            return _ako_cfg.meta_db
        hub_cfg = self.config.get('hub_integration', {})
        return hub_cfg.get('hub_meta_db', '')

    @property
    def llm_model(self) -> str:
        """获取 LLM 模型名称"""
        llm = self.config.get('llm_settings', {})
        return llm.get('model', 'deepseek-chat')

    @property
    def inbox_folder(self) -> str:
        """获取 Inbox 文件夹路径"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        folder = self.config.get('inbox_folder', 'Inbox')
        return os.path.join(base_dir, folder)
    
    def _get_current_profile(self) -> Dict[str, Any]:
        """获取当前激活的配置项详情"""
        profiles = self.config.get('profiles', {})
        if self.active_profile not in profiles:
            available = ', '.join(profiles.keys())
            raise ValueError(
                f"配置项 '{self.active_profile}' 不存在\n"
                f"可用的配置项: {available}"
            )
        return profiles[self.active_profile]
    
    def get_profile_info(self) -> str:
        """获取当前配置信息字符串"""
        profile = self._get_current_profile()
        profile_name = profile.get('name', self.active_profile)
        info = (
            f"当前配置: {profile_name} ({self.active_profile})\n"
            f"  数据库路径: {self.db_path}\n"
            f"  PDF 文件夹: {self.pdf_folder}\n"
            f"  Word 文件夹: {self.word_folder}\n"
            f"  PPT 文件夹: {self.ppt_folder}\n"
            f"  图片文件夹: {self.img_folder}\n"
            f"  集合名称: {self.collection_name}\n"
            f"  连接模式: {self.chroma_mode}"
        )
        if self.chroma_mode == 'remote':
            info += f"\n  服务器地址: {self.chroma_server_host}:{self.chroma_server_port}"
        return info
    
    def list_profiles(self) -> list:
        """列出所有可用的配置项"""
        profiles = self.config.get('profiles', {})
        result = []
        for key, value in profiles.items():
            current = " [当前]" if key == self.active_profile else ""
            result.append(f"  - {key}: {value.get('name', '未命名')}{current}")
        return result


# 全局配置实例(单例模式)
_config_instance = None

def get_config(config_file: str = None) -> ConfigLoader:
    """
    获取全局配置实例
    
    Args:
        config_file: 可选的配置文件路径
    
    Returns:
        ConfigLoader 实例
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigLoader(config_file)
    return _config_instance


def reload_config():
    """重新加载配置(用于动态切换配置)"""
    global _config_instance
    _config_instance = None
    return get_config()


if __name__ == "__main__":
    # 测试配置加载
    config = get_config()
    print("=" * 60)
    print("配置信息")
    print("=" * 60)
    print(config.get_profile_info())
    print("\n可用配置项:")
    for line in config.list_profiles():
        print(line)
    print("\n通用设置:")
    print(f"  分块大小: {config.chunk_size}")
    print(f"  重叠大小: {config.overlap}")
    print(f"  批量大小: {config.batch_size}")
    print(f"  嵌入模型: {config.embedding_model}")
    print(f"  OCR 语言: {config.ocr_languages}")
    print("=" * 60)
