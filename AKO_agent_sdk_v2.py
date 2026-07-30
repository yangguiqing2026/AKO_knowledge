#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AKO Agent SDK v2 — 自注册与健康探针框架
所有Agent引用此文件实现自注册、心跳上报、探针集成

版本: v2.0.0
作者: AKO_studio
"""

import os
import sys
import json
import time
import threading
import logging
from typing import Dict, List, Callable, Optional

import requests

logger = logging.getLogger("AKO_SDK_V2")


class AKOAgentSDK:
    """AKO Agent SDK v2 — 自注册与健康探针框架"""

    def __init__(self, config: Dict):
        """
        初始化 SDK

        Args:
            config: Agent配置字典，必须包含 agent_id, version, registry_url
        """
        self.config = config
        self.agent_id = config.get("agent_id", "unknown")
        self.version = config.get("version", "0.0.0")
        self.registry_url = config.get("registry_url", "http://localhost:8000")
        self.endpoint = config.get("endpoint", f"http://localhost:{config.get('port', 5000)}")
        self.heartbeat_interval = config.get("heartbeat_interval", 60)
        self.token = config.get("registry_token", "")

        self._business_probes: Optional[Callable] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running = False
        self._pid = os.getpid()

        self._load_card()

    def _load_card(self):
        """加载 AKO_agent_card.yaml 补充配置"""
        card_path = "AKO_agent_card.yaml"
        if os.path.exists(card_path):
            import yaml
            with open(card_path, "r", encoding="utf-8") as f:
                card_data = yaml.safe_load(f)
                # 从Card补充缺失的配置字段
                if "agent_id" not in self.config:
                    self.config["agent_id"] = card_data.get("agent_id", self.agent_id)
                if "version" not in self.config:
                    self.config["version"] = card_data.get("version", self.version)
                if "health" in card_data:
                    probe_config = card_data["health"]
                    self.heartbeat_interval = probe_config.get("probe_interval", self.heartbeat_interval)
                    self.config["dependencies"] = card_data.get("dependencies", [])
                    self.config["business_probes"] = probe_config.get("business_probes", [])
                logger.info(f"已加载Agent Card: {self.agent_id} v{self.version}")

    def register_business_probe(self, probe_func: Callable):
        """注册业务探针函数"""
        self._business_probes = probe_func

    def register(self) -> bool:
        """向Registry自注册"""
        try:
            payload = {
                "agent_id": self.agent_id,
                "version": self.version,
                "endpoint": self.endpoint,
                "token": self.token,
                "pid": self._pid,
                "status": "starting",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

            resp = requests.post(
                f"{self.registry_url}/api/v1/register",
                json=payload,
                timeout=10
            )

            if resp.status_code == 200:
                logger.info(f"Registry注册成功: {self.agent_id}")
                return True
            else:
                logger.warning(f"Registry注册返回异常: HTTP {resp.status_code}")
                return False

        except requests.exceptions.ConnectionError:
            logger.warning(f"无法连接Registry: {self.registry_url}，将在心跳时重试")
            return False
        except Exception as e:
            logger.error(f"Registry注册失败: {str(e)}")
            return False

    def start_heartbeat(self):
        """启动心跳线程"""
        if self._running:
            logger.warning("心跳服务已在运行")
            return

        self._running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        logger.info(f"心跳服务已启动 (间隔: {self.heartbeat_interval}s)")

    def stop_heartbeat(self):
        """停止心跳线程"""
        self._running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            logger.info("心跳服务已停止")

    def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.error(f"心跳上报异常: {str(e)}")

            time.sleep(self.heartbeat_interval)

    def _send_heartbeat(self):
        """发送心跳（含健康报告）"""
        health_report = self._collect_health_report()

        payload = {
            "agent_id": self.agent_id,
            "token": self.token,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "runtime": {
                "endpoint": self.endpoint,
                "pid": self._pid,
                "status": "running"
            },
            "health_report": health_report,
            "self_heal": {
                "requested": False,
                "reason": "",
                "attempted_actions": []
            }
        }

        try:
            resp = requests.post(
                f"{self.registry_url}/api/v1/heartbeat",
                json=payload,
                timeout=10
            )
            if resp.status_code == 200:
                logger.debug(f"心跳上报成功: {self.agent_id}")
            else:
                logger.warning(f"心跳上报异常: HTTP {resp.status_code}")

        except requests.exceptions.ConnectionError:
            logger.debug(f"Registry不可达: {self.registry_url}")

    def _collect_health_report(self) -> Dict:
        """收集健康报告"""
        business_checks = []
        if self._business_probes:
            try:
                business_checks = self._business_probes()
            except Exception as e:
                logger.error(f"业务探针执行异常: {str(e)}")

        # 计算整体状态
        overall = "healthy"
        for check in business_checks:
            if check and check.get("status") == "fail":
                overall = "critical"
                break
            if check and check.get("status") == "warn":
                overall = "warning"

        return {
            "overall": overall,
            "business": {"checks": business_checks},
            "system": {"checks": self._collect_system_checks()}
        }

    def _collect_system_checks(self) -> List[Dict]:
        """收集系统探针检查结果（SDK内置）"""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        checks = [
            {
                "name": "进程状态",
                "status": "pass",
                "pid": self._pid,
                "timestamp": timestamp
            }
        ]

        try:
            import psutil
            thresholds = self.config.get("system_probes", {})

            # CPU
            cpu = psutil.cpu_percent(interval=0.5)
            cpu_threshold = thresholds.get("cpu", 80)
            checks.append({
                "name": "CPU使用率",
                "status": "pass" if cpu < cpu_threshold else "warn",
                "value": f"{cpu}%",
                "threshold": f"{cpu_threshold}%",
                "timestamp": timestamp
            })

            # 内存
            memory = psutil.virtual_memory()
            mem_threshold = thresholds.get("memory", 80)
            checks.append({
                "name": "内存使用率",
                "status": "pass" if memory.percent < mem_threshold else "warn",
                "value": f"{memory.percent}%",
                "available": f"{memory.available // 1024 // 1024}MB",
                "threshold": f"{mem_threshold}%",
                "timestamp": timestamp
            })

            # 磁盘
            disk = psutil.disk_usage('/')
            disk_threshold = thresholds.get("disk", 80)
            checks.append({
                "name": "磁盘空间",
                "status": "pass" if disk.percent < disk_threshold else "warn",
                "value": f"{disk.percent}%",
                "free": f"{disk.free // 1024 // 1024 // 1024}GB",
                "threshold": f"{disk_threshold}%",
                "timestamp": timestamp
            })

        except ImportError:
            checks.append({
                "name": "系统探针",
                "status": "warn",
                "detail": "psutil未安装，系统探针不可用",
                "timestamp": timestamp
            })

        return checks


# ==== 使用示例 ====
if __name__ == "__main__":
    config = {
        "agent_id": "AKO_test_agent",
        "version": "1.0.0",
        "registry_url": "http://localhost:8000",
        "port": 5000,
        "heartbeat_interval": 30
    }

    sdk = AKOAgentSDK(config)
    sdk.register()
    sdk.start_heartbeat()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sdk.stop_heartbeat()
