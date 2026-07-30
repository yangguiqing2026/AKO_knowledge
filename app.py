#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AKO Agent 入口文件
自动集成 SDK v2 注册 + 业务探针
"""

import os
import sys
import yaml
import logging

from AKO_agent_sdk_v2 import AKOAgentSDK
from probes.business_probes import BusinessProbes

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/agent.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("AKO_Agent")


def load_config() -> dict:
    """加载配置文件"""
    config = {}

    # 加载 config.yaml
    config_paths = ["config.yaml", "config/config.yaml"]
    for path in config_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                config.update(yaml.safe_load(f))
            logger.info(f"已加载配置文件: {path}")
            break

    # 从 secrets.env 加载环境变量
    if os.path.exists("secrets.env"):
        with open("secrets.env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    return config


def main():
    """主入口"""
    logger.info("=" * 60)
    logger.info("AKO Agent 启动中...")
    logger.info("=" * 60)

    # 1. 加载配置
    config = load_config()

    # 2. 初始化 SDK
    sdk = AKOAgentSDK(config)
    logger.info(f"Agent SDK 初始化完成: {sdk.agent_id} v{sdk.version}")

    # 3. 注册业务探针
    probes = BusinessProbes(config)
    sdk.register_business_probe(probes.run_all)
    logger.info("业务探针已注册")

    # 4. 向 Registry 自注册
    sdk.register()
    logger.info(f"已向 Registry 注册: {sdk.registry_url}")

    # 5. 启动心跳
    sdk.start_heartbeat()
    logger.info("心跳服务已启动")

    # 6. 启动业务服务
    logger.info("Agent 就绪，等待任务...")

    try:
        # 保持进程运行
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到停止信号，优雅关闭...")
        sdk.stop_heartbeat()
        logger.info("Agent 已停止")


if __name__ == "__main__":
    main()
