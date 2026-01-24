#!/usr/bin/env python3
"""
Utilities for monitoring and maintenance of LLM code review system.
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import ReviewConfig
from review_core import LLMReviewer, ReviewResult


class MonitoringUtils:
    """Utilities for monitoring LLM code review system."""
    
    def __init__(self):
        self.config = ReviewConfig()
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)
    
    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "checks": {}
        }
        
        # Check configuration
        config_status = self._check_configuration()
        results["checks"]["configuration"] = config_status
        
        # Check git repository
        git_status = self._check_git_repository()
        results["checks"]["git"] = git_status
        
        # Check LLM connection
        llm_status = self._check_llm_connection()
        results["checks"]["llm"] = llm_status
        
        # Check hooks installation
        hooks_status = self._check_hooks()
        results["checks"]["hooks"] = hooks_status
        
        # Overall status
        results["overall_status"] = "healthy" if all(
            check.get("status") == "ok" for check in results["checks"].values()
        ) else "unhealthy"
        
        return results
    
    def _check_configuration(self) -> Dict[str, Any]:
        """Check configuration files and environment."""
        result = {"status": "ok", "details": {}}
        
        # Check config file
        if Path(self.config.config_file).exists():
            result["details"]["config_file"] = "exists"
        else:
            result["details"]["config_file"] = "missing"
            result["status"] = "warning"
        
        # Check API key
        api_key = self.config.get_api_key()
        if api_key:
            result["details"]["api_key"] = "configured"
        else:
            result["details"]["api_key"] = "missing"
            result["status"] = "error"
        
        # Check Python dependencies
        try:
            import openai
            result["details"]["dependencies"] = "ok"
        except ImportError:
            result["details"]["dependencies"] = "missing"
            result["status"] = "error"
        
        return result
    
    def _check_git_repository(self) -> Dict[str, Any]:
        """Check git repository status."""
        result = {"status": "ok", "details": {}}
        
        import subprocess
        try:
            # Check if in git repository
            subprocess.run(["git", "rev-parse", "--git-dir"], 
                         check=True, capture_output=True)
            result["details"]["repository"] = "ok"
            
            # Check for staged changes
            staged_result = subprocess.run(["git", "diff", "--cached", "--name-only"], 
                                        capture_output=True, text=True)
            staged_files = staged_result.stdout.strip().split('\n') if staged_result.stdout.strip() else []
            result["details"]["staged_files"] = len(staged_files)
            
        except subprocess.CalledProcessError:
            result["details"]["repository"] = "not_a_repo"
            result["status"] = "error"
        except FileNotFoundError:
            result["details"]["repository"] = "git_not_found"
            result["status"] = "error"
        
        return result
    
    def _check_llm_connection(self) -> Dict[str, Any]:
        """Check LLM connection."""
        result = {"status": "ok", "details": {}}
        
        try:
            reviewer = LLMReviewer(self.config)
            if reviewer.test_connection():
                result["details"]["connection"] = "ok"
                result["details"]["model"] = self.config.get("llm.model")
            else:
                result["details"]["connection"] = "failed"
                result["status"] = "error"
        except Exception as e:
            result["details"]["connection"] = f"error: {str(e)}"
            result["status"] = "error"
        
        return result
    
    def _check_hooks(self) -> Dict[str, Any]:
        """Check git hooks installation."""
        result = {"status": "ok", "details": {}}
        
        hooks_dir = Path(".git/hooks")
        required_hooks = ["pre-commit", "pre-push"]
        
        for hook in required_hooks:
            hook_file = hooks_dir / hook
            if hook_file.exists() and os.access(hook_file, os.X_OK):
                result["details"][hook] = "installed"
            else:
                result["details"][hook] = "missing"
                result["status"] = "warning"
        
        return result
    
    def log_review_result(self, result: ReviewResult, metadata: Optional[Dict[str, Any]] = None):
        """Log review results for monitoring."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "result": {
                "status": result.status,
                "critical_count": len(result.critical_issues),
                "warning_count": len(result.warnings),
                "suggestion_count": len(result.suggestions),
                "fallback_used": result.fallback_used
            },
            "metadata": metadata if metadata is not None else {}
        }
        
        # Add to daily log file
        log_file = self.logs_dir / f"reviews_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def generate_report(self, days: int = 7) -> Dict[str, Any]:
        """Generate monitoring report for specified period."""
        report = {
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "summary": {},
            "details": []
        }
        
        # Collect logs from specified period
        all_entries = []
        
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            log_file = self.logs_dir / f"reviews_{date}.jsonl"
            
            if log_file.exists():
                with open(log_file, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            all_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        
        if not all_entries:
            report["summary"] = {"total_reviews": 0}
            return report
        
        # Calculate summary statistics
        total_reviews = len(all_entries)
        successful_reviews = sum(1 for e in all_entries if e["result"]["status"] == "success")
        unavailable_reviews = sum(1 for e in all_entries if e["result"]["status"] == "model_unavailable")
        total_critical = sum(e["result"]["critical_count"] for e in all_entries)
        total_warnings = sum(e["result"]["warning_count"] for e in all_entries)
        
        report["summary"] = {
            "total_reviews": total_reviews,
            "successful_reviews": successful_reviews,
            "unavailable_reviews": unavailable_reviews,
            "success_rate": successful_reviews / total_reviews * 100 if total_reviews > 0 else 0,
            "total_critical_issues": total_critical,
            "total_warnings": total_warnings,
            "avg_critical_per_review": total_critical / total_reviews if total_reviews > 0 else 0,
            "avg_warnings_per_review": total_warnings / total_reviews if total_reviews > 0 else 0
        }
        
        # Add recent entries for details
        report["details"] = all_entries[-10:]  # Last 10 reviews
        
        return report


def main():
    """CLI interface for monitoring utilities."""
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM Code Review Monitoring Utilities")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Health check command
    health_parser = subparsers.add_parser('health', help='Perform health check')
    
    # Report command
    report_parser = subparsers.add_parser('report', help='Generate monitoring report')
    report_parser.add_argument('--days', type=int, default=7, help='Number of days to include in report')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    monitor = MonitoringUtils()
    
    if args.command == 'health':
        print("🏥 LLM Code Review Health Check")
        print("=" * 40)
        
        health = monitor.health_check()
        
        print(f"Overall Status: {health['overall_status'].upper()}")
        print("")
        
        for check_name, check_result in health['checks'].items():
            status_icon = "✅" if check_result['status'] == 'ok' else "⚠️" if check_result['status'] == 'warning' else "❌"
            print(f"{status_icon} {check_name.title()}: {check_result['status']}")
            
            for detail_name, detail_value in check_result['details'].items():
                print(f"   • {detail_name}: {detail_value}")
            print("")
    
    elif args.command == 'report':
        print(f"📊 LLM Code Review Report (Last {args.days} days)")
        print("=" * 50)
        
        report = monitor.generate_report(args.days)
        
        summary = report['summary']
        print(f"Total Reviews: {summary['total_reviews']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        print(f"Model Unavailable: {summary['unavailable_reviews']}")
        print(f"Total Critical Issues: {summary['total_critical_issues']}")
        print(f"Total Warnings: {summary['total_warnings']}")
        print(f"Avg Critical/Review: {summary['avg_critical_per_review']:.1f}")
        print(f"Avg Warnings/Review: {summary['avg_warnings_per_review']:.1f}")


if __name__ == "__main__":
    main()