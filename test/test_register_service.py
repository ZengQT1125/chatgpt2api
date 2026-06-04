import unittest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path
import json

from services.register.mail_provider import _next_domain
from services.register_service import RegisterService

class RegisterServiceTests(unittest.TestCase):
    def test_next_domain_random(self):
        # 测试多个域名时的随机选择
        domains = ["test1.com", "test2.com", "test3.com"]
        choices = set()
        for _ in range(100):
            choices.add(_next_domain(domains))
        # 概率上，100次选择应该能够覆盖这三个域名（除非运气极差）
        self.assertEqual(len(choices), 3)
        self.assertTrue(choices.issubset(set(domains)))

    def test_consecutive_failure_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_file = Path(tmp_dir) / "register.json"
            
            # 初始化配置，设置 enabled=False 以防构造函数自动启动后台线程
            initial_cfg = {
                "total": 10,
                "threads": 1,
                "mode": "total",
                "enabled": False,
                "max_consecutive_failures": 2,
                "mail": {
                    "request_timeout": 30,
                    "wait_timeout": 30,
                    "wait_interval": 2,
                    "providers": []
                }
            }
            store_file.write_text(json.dumps(initial_cfg), encoding="utf-8")
            
            service = RegisterService(store_file)
            service._config["enabled"] = True
            
            # Mock worker 让它总是返回失败
            mock_worker = MagicMock(return_value={"ok": False})
            
            with patch("services.register.openai_register.worker", mock_worker):
                service._run()
                
            # 应该在第 2 次连续失败后停止，enabled 自动设为 False
            self.assertFalse(service.get()["enabled"])
            # worker 只被调用了 2 次，而不是 10 次
            self.assertEqual(mock_worker.call_count, 2)
            self.assertEqual(service.get()["stats"]["fail"], 2)

    def test_consecutive_failure_reset_on_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_file = Path(tmp_dir) / "register.json"
            
            # 初始化配置，设置 enabled=False
            initial_cfg = {
                "total": 3,
                "threads": 1,
                "mode": "total",
                "enabled": False,
                "max_consecutive_failures": 2,
                "mail": {
                    "request_timeout": 30,
                    "wait_timeout": 30,
                    "wait_interval": 2,
                    "providers": []
                }
            }
            store_file.write_text(json.dumps(initial_cfg), encoding="utf-8")
            
            service = RegisterService(store_file)
            service._config["enabled"] = True
            
            # Mock worker：第 1 次失败，第 2 次成功，第 3 次失败
            call_results = [{"ok": False}, {"ok": True}, {"ok": False}]
            def side_effect(index):
                return call_results[index - 1]
            mock_worker = MagicMock(side_effect=side_effect)
            
            with patch("services.register.openai_register.worker", mock_worker):
                service._run()
                
            # 虽然一共失败了 2 次，但因为中间成功的重置，最大连续失败只有 1 次，没有触发连续 2 次失败退出，任务应该把 total (3次) 跑完
            self.assertEqual(mock_worker.call_count, 3)
            self.assertEqual(service.get()["stats"]["success"], 1)
            self.assertEqual(service.get()["stats"]["fail"], 2)

if __name__ == "__main__":
    unittest.main()
