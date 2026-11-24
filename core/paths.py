"""以源码位置定位项目资源，不依赖当前工作目录。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
