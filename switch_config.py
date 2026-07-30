"""
配置切换工具 - 快速在不同电脑配置间切换
用法: python switch_config.py [computer_a|computer_b|...]
"""
import sys
import json
import os


def switch_profile(profile_name: str):
    """切换到指定的配置项"""
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    
    # 读取配置文件
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ 配置文件不存在: {config_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ 配置文件格式错误: {e}")
        return False
    
    # 检查配置项是否存在
    profiles = config.get('profiles', {})
    if profile_name not in profiles:
        print(f"❌ 配置项 '{profile_name}' 不存在")
        print(f"\n可用的配置项:")
        for key in profiles.keys():
            print(f"  - {key}")
        return False
    
    # 更新 active_profile
    old_profile = config.get('active_profile', '')
    config['active_profile'] = profile_name
    
    # 保存配置文件
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✅ 配置已切换: {old_profile} → {profile_name}")
        
        # 显示新配置信息
        new_profile = profiles[profile_name]
        print(f"\n新配置信息:")
        print(f"  名称: {new_profile.get('name', profile_name)}")
        print(f"  PDF 文件夹: {new_profile.get('pdf_folder', 'N/A')}")
        print(f"  集合名称: {new_profile.get('collection_name', 'N/A')}")
        return True
    except Exception as e:
        print(f"❌ 保存配置文件失败: {e}")
        return False


def show_current_profile():
    """显示当前配置"""
    from config_loader import get_config
    
    try:
        config = get_config()
        print("=" * 60)
        print("当前配置")
        print("=" * 60)
        print(config.get_profile_info())
        print("\n可用配置项:")
        for line in config.list_profiles():
            print(line)
        print("=" * 60)
    except Exception as e:
        print(f"❌ 读取配置失败: {e}")


def main():
    if len(sys.argv) > 1:
        # 切换配置
        profile_name = sys.argv[1]
        switch_profile(profile_name)
    else:
        # 显示当前配置
        show_current_profile()


if __name__ == "__main__":
    main()
