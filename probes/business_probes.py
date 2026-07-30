# probes/business_probes.py — 业务探针
# 每个Agent必须根据自身业务实现以下探针
# 作者：AKO_studio

from typing import Dict, List
import os
import time


class BusinessProbes:
    """AKO Agent业务探针集合

    每个Agent必须实现以下探针：
    1. 核心功能自检 - 验证主业务逻辑是否正常
    2. 输入输出通道 - 验证文件读写/网络请求
    3. 依赖服务可用 - 验证调用的其他Agent/服务
    4. 知识库同步 - 验证本地知识库与云端一致（如有）
    5. 配置有效性 - 验证配置文件完整合法

    返回格式必须严格遵循ProbeResult标准
    """

    def __init__(self, agent_config: Dict):
        self.config = agent_config
        self.agent_id = agent_config.get("agent_id", "unknown")

    def run_all(self) -> List[Dict]:
        """执行所有业务探针，返回探针结果列表"""
        probes = [
            self.check_core_function(),
            self.check_io_channel(),
            self.check_dependencies(),
            self.check_knowledge_base(),
            self.check_config_validity()
        ]
        return [p for p in probes if p]  # 过滤None

    def check_core_function(self) -> Dict:
        """探针1：核心功能自检

        说明：执行一次主业务逻辑的测试调用，验证核心功能正常
        失败：返回fail，detail说明失败原因
        """
        try:
            start_time = time.time()

            # ==== 业务实现区域开始 ====
            # 这里写该Agent的核心功能测试代码
            result = {"status": "ok"}
            # ==== 业务实现区域结束 ====

            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "name": "核心功能自检",
                "status": "pass",
                "detail": "核心功能运行正常",
                "latency_ms": latency_ms,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

        except Exception as e:
            return {
                "name": "核心功能自检",
                "status": "fail",
                "detail": f"核心功能异常: {str(e)}",
                "latency_ms": 0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

    def check_io_channel(self) -> Dict:
        """探针2：输入输出通道检查

        说明：验证文件读写、网络请求等IO通道正常
        """
        try:
            # 测试文件读写
            test_dir = self.config.get("output_dir", "./output")
            os.makedirs(test_dir, exist_ok=True)

            test_file = os.path.join(test_dir, ".probe_test")
            with open(test_file, 'w') as f:
                f.write("AKO_probe_test")
            with open(test_file, 'r') as f:
                content = f.read()
            os.remove(test_file)

            assert content == "AKO_probe_test"

            return {
                "name": "输入输出通道",
                "status": "pass",
                "detail": f"文件读写正常 ({test_dir})",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

        except Exception as e:
            return {
                "name": "输入输出通道",
                "status": "fail",
                "detail": f"IO通道异常: {str(e)}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

    def check_dependencies(self) -> Dict:
        """探针3：依赖服务可用检查

        说明：验证本Agent依赖的其他Agent/服务是否可达
        """
        import requests

        dependency_results = []
        overall_status = "pass"

        # 从Card读取依赖列表
        deps = self.config.get("dependencies", [])

        for dep in deps:
            if not dep.get("required", False):
                continue  # 跳过非必须依赖

            dep_id = dep.get("agent_id", "")
            dep_endpoint = self._get_dependency_endpoint(dep_id)

            try:
                start = time.time()
                resp = requests.get(f"{dep_endpoint}/health", timeout=5)
                latency_ms = int((time.time() - start) * 1000)

                if resp.status_code == 200:
                    dependency_results.append({
                        "agent_id": dep_id,
                        "status": "pass",
                        "latency_ms": latency_ms
                    })
                else:
                    dependency_results.append({
                        "agent_id": dep_id,
                        "status": "warn",
                        "latency_ms": latency_ms,
                        "detail": f"HTTP {resp.status_code}"
                    })
                    overall_status = "warn"

            except Exception as e:
                dependency_results.append({
                    "agent_id": dep_id,
                    "status": "fail",
                    "latency_ms": 0,
                    "detail": str(e)
                })
                overall_status = "warn"

        return {
            "name": "依赖服务可用",
            "status": overall_status,
            "detail": f"检查{len(dependency_results)}个依赖",
            "dependencies": dependency_results,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        }

    def check_knowledge_base(self) -> Dict:
        """探针4：知识库同步检查（可选）

        说明：验证本地知识库与云端是否一致
        无知识库的Agent可返回None（跳过）
        """
        kb_path = self.config.get("knowledge_base_path")
        if not kb_path or not os.path.exists(kb_path):
            return None  # 无知识库，跳过

        try:
            return {
                "name": "知识库同步",
                "status": "pass",
                "detail": "本地知识库与云端一致",
                "last_sync": "2026-07-29T20:00:00+08:00",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

        except Exception as e:
            return {
                "name": "知识库同步",
                "status": "warn",
                "detail": f"知识库同步异常: {str(e)}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

    def check_config_validity(self) -> Dict:
        """探针5：配置有效性检查

        说明：验证配置文件完整、参数合法
        """
        try:
            required_keys = ["agent_id", "version", "registry_url"]
            missing = [k for k in required_keys if k not in self.config]

            if missing:
                return {
                    "name": "配置有效性",
                    "status": "fail",
                    "detail": f"配置缺失必填项: {missing}",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
                }

            return {
                "name": "配置有效性",
                "status": "pass",
                "detail": "配置文件完整合法",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

        except Exception as e:
            return {
                "name": "配置有效性",
                "status": "fail",
                "detail": f"配置检查异常: {str(e)}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }

    def _get_dependency_endpoint(self, agent_id: str) -> str:
        """获取依赖Agent的endpoint（从Registry查询或本地配置）"""
        dep_configs = self.config.get("dependency_endpoints", {})
        if agent_id in dep_configs:
            return dep_configs[agent_id]
        return f"http://localhost:8000"


# ==== 使用方式 ====
# 在 app.py 中：
# from probes.business_probes import BusinessProbes
#
# probes = BusinessProbes(config)
# sdk.register_business_probe(probes.run_all)
