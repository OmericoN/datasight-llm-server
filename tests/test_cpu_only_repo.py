from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class CpuOnlyRepositoryTests(unittest.TestCase):
    def test_gateway_repo_does_not_include_gpu_backend_artifacts(self) -> None:
        forbidden_paths = [
            REPO_ROOT / "gpu" / "Dockerfile",
            REPO_ROOT / "gpu" / "entrypoint-vllm.sh",
            REPO_ROOT / "dsri" / "vllm-gpu-deployment.yaml",
            REPO_ROOT / "dsri" / "vllm-gpu-service.yaml",
            REPO_ROOT / "dsri" / "vllm-gpu-pvc.yaml",
        ]

        existing_paths = [path for path in forbidden_paths if path.exists()]

        self.assertEqual(existing_paths, [])

    def test_gateway_dockerfile_stays_cpu_only(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("vllm", dockerfile.lower())
        self.assertNotIn("cuda", dockerfile.lower())
        self.assertNotIn("nvidia.com/gpu", dockerfile.lower())


if __name__ == "__main__":
    unittest.main()
