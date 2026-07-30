# -*- coding: utf-8 -*-
"""
Gbrain 夜间 Agent — 自动维护 / git diff 学习轨迹

夜间任务:
  1. 执行完整发酵周期 (重建图谱 + 分层富化)
  2. 自动 git commit (记录学习轨迹)
  3. 生成发酵日报
  4. 清理孤立概念 (30天无引用的 stub)
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from gbrain_ferment import FermentEngine, create_engine


class NightlyAgent:
    """
    夜间自动维护 Agent

    使用方式:
      python -m gbrain_nightly         # 手动运行一次
      python -m gbrain_nightly --cron  # 定时任务模式 (安静输出)
    """

    def __init__(
        self,
        db_path: str = "",
        vault_root: str = r"D:\AKOBUILD",
        collection_name: str = "ako_photos",
        git_auto_commit: bool = True,
    ):
        self.db_path = db_path or str(Path(__file__).resolve().parent)
        self.vault_root = vault_root
        self.collection_name = collection_name
        self.git_auto_commit = git_auto_commit
        self.engine: Optional[FermentEngine] = None

    def run(self, full_graph: bool = True, quiet: bool = False) -> dict:
        """
        执行夜间维护任务

        Returns:
            完整的维护报告
        """
        now = datetime.datetime.now().isoformat()
        report: dict = {
            "timestamp": now,
            "task": "gbrain_nightly_maintenance",
            "ferment": {},
            "cleanup": {},
            "git": {},
            "diff_summary": "",
            "errors": [],
        }

        if not quiet:
            print(f"[Nightly] ========== Gbrain 夜间维护开始 ==========")
            print(f"[Nightly] 时间: {now}")

        # Step 1: 初始化引擎
        try:
            self.engine = create_engine(
                db_path=self.db_path,
                collection_name=self.collection_name,
                vault_root=self.vault_root,
            )
        except Exception as e:
            report["errors"].append(f"引擎初始化失败: {e}")
            return report

        # Step 2: 执行发酵
        if not quiet:
            print(f"[Nightly] 执行发酵周期...")
        try:
            ferment_report = self.engine.ferment(full_graph=full_graph)
            report["ferment"] = ferment_report
            if not quiet:
                print(f"[Nightly] 发酵完成: "
                      f"新建 {ferment_report['stubs_created']} stubs, "
                      f"升级 basic={ferment_report['upgrades_basic']}, "
                      f"full={ferment_report['upgrades_full']}, "
                      f"总页面 {ferment_report['total_pages']}")
        except Exception as e:
            report["errors"].append(f"发酵失败: {e}")
            if not quiet:
                print(f"[Nightly] 发酵失败: {e}")
            return report

        # Step 3: 清理孤立概念
        if not quiet:
            print(f"[Nightly] 清理孤立概念...")
        try:
            cleanup_report = self._cleanup_orphans()
            report["cleanup"] = cleanup_report
            if not quiet:
                print(f"[Nightly] 清理: 删除 {cleanup_report.get('removed', 0)} 个孤立概念")
        except Exception as e:
            report["errors"].append(f"清理失败: {e}")

        # Step 4: 生成差异摘要
        report["diff_summary"] = self._generate_diff_summary(report)

        # Step 5: Git 自动提交
        if self.git_auto_commit:
            if not quiet:
                print(f"[Nightly] Git auto-commit...")
            try:
                git_report = self._git_auto_commit(report)
                report["git"] = git_report
                if not quiet:
                    print(f"[Nightly] Git: {git_report.get('message', 'N/A')}")
            except Exception as e:
                report["errors"].append(f"Git 提交失败: {e}")
                if not quiet:
                    print(f"[Nightly] Git 提交失败: {e}")

        if not quiet:
            print(f"[Nightly] ========== 夜间维护完成 ==========")

        return report

    # ==================================================================
    # 清理孤立概念
    # ==================================================================

    def _cleanup_orphans(self, orphan_days: int = 30) -> dict:
        """
        清理 30 天以上无新引用的 stub 概念
        """
        if self.engine is None:
            return {"removed": 0, "message": "引擎未初始化"}

        now = datetime.datetime.now()
        removed = 0
        removed_names = []

        for page in self.engine.store.get_stubs():
            # 检查是否长时间未更新
            if page.last_seen:
                try:
                    last_seen = datetime.datetime.fromisoformat(page.last_seen)
                    if (now - last_seen).days > orphan_days:
                        self.engine.store.delete(page.concept_id)
                        removed += 1
                        removed_names.append(page.concept_name)
                except (ValueError, TypeError):
                    pass

        return {
            "removed": removed,
            "removed_names": removed_names[:20],
            "orphan_threshold_days": orphan_days,
            "remaining_stubs": len(self.engine.store.get_stubs()),
        }

    # ==================================================================
    # 差异摘要
    # ==================================================================

    def _generate_diff_summary(self, report: dict) -> str:
        """
        生成学习轨迹摘要 — 相当于 git diff 的人类可读版本
        """
        ferment = report.get("ferment", {})
        cleanup = report.get("cleanup", {})

        parts = []
        graph = ferment.get("graph_stats", {})

        if graph:
            parts.append(
                f"图谱: {graph.get('total_concepts', 0)} 概念, "
                f"{graph.get('total_edges', 0)} 边, "
                f"平均 {graph.get('avg_mentions', 0):.1f} 次引用"
            )

        stubs = ferment.get("stubs_created", 0)
        if stubs:
            parts.append(f"新建 {stubs} 个 stub 页面")

        upgrades = []
        if ferment.get("upgrades_basic"):
            upgrades.append(f"basic={ferment['upgrades_basic']}")
        if ferment.get("upgrades_full"):
            upgrades.append(f"full={ferment['upgrades_full']}")
        if upgrades:
            parts.append(f"升级: {', '.join(upgrades)}")

        enriched = []
        if ferment.get("enriched_basic"):
            enriched.append(f"基础富化 {ferment['enriched_basic']}")
        if ferment.get("enriched_full"):
            enriched.append(f"完整富化 {ferment['enriched_full']}")
        if enriched:
            parts.append(f"富化: {', '.join(enriched)}")

        removed = cleanup.get("removed", 0)
        if removed:
            parts.append(f"清理 {removed} 个孤立概念")

        total = ferment.get("total_pages", 0)
        parts.insert(0, f"总计 {total} 个概念页面")

        return " | ".join(parts)

    # ==================================================================
    # Git 自动提交
    # ==================================================================

    def _git_auto_commit(self, report: dict) -> dict:
        """
        自动提交 gbrain_graph.json 到 git，记录学习轨迹

        提交信息格式:
          [Gbrain] 夜间发酵: +3 stubs, ↑2 basic, ↑1 full | 总计 127 概念
        """
        repo_root = self.db_path

        # 构建提交信息
        ferment = report.get("ferment", {})
        upgrades = []
        if ferment.get("upgrades_basic"):
            upgrades.append(f"↑{ferment['upgrades_basic']} basic")
        if ferment.get("upgrades_full"):
            upgrades.append(f"↑{ferment['upgrades_full']} full")

        msg_parts = [f"+{ferment.get('stubs_created', 0)} stubs"]
        msg_parts.extend(upgrades)
        msg_parts.append(f"总计 {ferment.get('total_pages', 0)} 概念")

        commit_msg = f"[Gbrain] 夜间发酵: {', '.join(msg_parts)}"

        # 只提交 data/gbrain_graph.json
        data_file = os.path.join(repo_root, "data", "gbrain_graph.json")

        try:
            # 检查是否有变更
            result = subprocess.run(
                ["git", "-C", repo_root, "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            changed_files = result.stdout.strip().split("\n") if result.stdout.strip() else []

            if "data/gbrain_graph.json" not in changed_files:
                return {
                    "committed": False,
                    "message": "无变更，跳过提交",
                    "commit_hash": "",
                }

            # 添加并提交
            subprocess.run(
                ["git", "-C", repo_root, "add", "data/gbrain_graph.json"],
                capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-m", commit_msg],
                capture_output=True, text=True, timeout=10,
            )

            # 获取 commit hash
            hash_result = subprocess.run(
                ["git", "-C", repo_root, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            commit_hash = hash_result.stdout.strip()

            return {
                "committed": True,
                "message": commit_msg,
                "commit_hash": commit_hash,
            }
        except FileNotFoundError:
            return {
                "committed": False,
                "message": "git 命令不可用",
                "commit_hash": "",
            }
        except Exception as e:
            return {
                "committed": False,
                "message": f"git 操作异常: {e}",
                "commit_hash": "",
            }

    # ==================================================================
    # 日报生成
    # ==================================================================

    def generate_daily_report(self) -> dict:
        """生成发酵日报"""
        report = self.run(full_graph=True, quiet=True)

        ferment = report.get("ferment", {})
        graph = ferment.get("graph_stats", {})

        # 按等级分类
        stubs = len(self.engine.store.get_stubs()) if self.engine else 0
        basics = len(self.engine.store.get_by_level(1)) if self.engine else 0
        fulls = len(self.engine.store.get_full()) if self.engine else 0

        # TOP 概念 (按引用次数)
        top_concepts = []
        if self.engine:
            all_pages = sorted(
                self.engine.store.get_all().values(),
                key=lambda p: p.mention_count,
                reverse=True,
            )
            for p in all_pages[:10]:
                top_concepts.append({
                    "name": p.concept_name,
                    "mentions": p.mention_count,
                    "level": p.enrichment_level,
                    "has_compiled_truth": p.compiled_truth is not None,
                })

        return {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "summary": report["diff_summary"],
            "distribution": {
                "stubs": stubs,
                "basic": basics,
                "full": fulls,
            },
            "top_concepts": top_concepts,
            "graph_stats": {
                "total_concepts": graph.get("total_concepts", 0),
                "total_edges": graph.get("total_edges", 0),
                "max_mentions": graph.get("max_mentions", 0),
                "avg_mentions": round(graph.get("avg_mentions", 0), 2),
            },
            "errors": report.get("errors", []),
        }


# ==================== 命令行入口 ====================

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Gbrain 夜间维护 Agent")
    ap.add_argument("--cron", action="store_true", help="定时任务模式 (安静)")
    ap.add_argument("--no-git", action="store_true", help="跳过 git 自动提交")
    ap.add_argument("--vault", default=r"D:\AKOBUILD", help="Obsidian vault 路径")
    ap.add_argument("--daily-report", action="store_true", help="生成日报")
    args = ap.parse_args()

    agent = NightlyAgent(
        db_path=str(Path(__file__).resolve().parent),
        vault_root=args.vault,
        git_auto_commit=not args.no_git,
    )

    if args.daily_report:
        result = agent.generate_daily_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = agent.run(full_graph=True, quiet=args.cron)
        if not args.cron:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("errors"):
            print(f"[Nightly ERROR] {result['errors']}", file=sys.stderr)

    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())