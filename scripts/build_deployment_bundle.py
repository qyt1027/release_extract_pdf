"""从当前工作区生成不含凭据与业务数据的独立代码部署包。"""

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    'core', 'commands', 'web', 'processing', 'classification', 'storage',
    'parsers', 'metadata', 'policy', 'policy_mcp', 'scripts', 'examples', 'tests', 'docs',
)
ROOT_FILES = ('main.py', 'api.py', 'README.md', 'HANDOFF.md', 'requirements.txt',
              'requirements-dev.txt', '.env.example', '.gitignore')
SUFFIXES = {'.py', '.md', '.txt', '.csv', '.json', '.html', '.css', '.js', '.sql'}


def build_bundle(output_root: Path) -> Path:
    """按显式目录和文件类型打包，避免复制日志、源资料与本地环境。"""
    name = 'extract_pdf_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    destination = output_root.resolve() / name
    if destination == PROJECT_ROOT or PROJECT_ROOT.is_relative_to(destination):
        raise ValueError('部署目录不能覆盖项目根目录')
    destination.mkdir(parents=True, exist_ok=False)
    files = [PROJECT_ROOT / name for name in ROOT_FILES]
    for package in PACKAGES:
        files.extend(p for p in (PROJECT_ROOT / package).rglob('*')
                     if p.is_file() and p.suffix in SUFFIXES
                     and '__pycache__' not in p.parts and not p.is_symlink())
    for source in files:
        target = destination / source.relative_to(PROJECT_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    installed = {}
    pinned = ['# 本次打包环境中验证过的直接运行依赖；传递依赖仍由安装器解析。']
    for line in (PROJECT_ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.match(r'([\w.-]+)(\[[^]]+\])?', line)
        if not match:
            raise ValueError(f'无法识别依赖声明: {line}')
        package, extras = match.group(1), match.group(2) or ''
        version = importlib.metadata.version(package)
        installed[package] = version
        pinned.append(f'{package}{extras}=={version}')
    (destination / 'requirements-tested.txt').write_text('\n'.join(pinned) + '\n', encoding='utf-8')
    (destination / 'DEPLOY.md').write_text(
        '# 部署入口\n\n请先阅读 [新环境部署说明](docs/deployment.md)，复制 `.env.example` 为 `.env` 后填写配置。\n'
        '\n该文件夹不包含本机凭据、数据库数据、原始资料和模型权重。\n', encoding='utf-8')
    info = {'created_at': datetime.now().astimezone().isoformat(), 'python': sys.version,
            'runtime_dependencies': installed, 'includes_database_data': False,
            'includes_model_weights': False, 'includes_credentials': False}
    (destination / 'build-info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = []
    for p in sorted(destination.rglob('*')):
        if p.is_file():
            manifest.append({'path': p.relative_to(destination).as_posix(), 'size': p.stat().st_size,
                             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (destination / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive_path = destination.with_suffix('.zip')
    with ZipFile(archive_path, 'x', compression=ZIP_DEFLATED) as archive:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                archive.write(p, f'{destination.name}/{p.relative_to(destination).as_posix()}')
    print(json.dumps({'folder': str(destination), 'archive': str(archive_path), 'files': len(manifest) + 1}, ensure_ascii=False))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description='生成独立代码部署文件夹及 ZIP，不复制真实凭据或业务数据')
    parser.add_argument('--output-dir', type=Path, default=PROJECT_ROOT / 'outputs' / 'deployment')
    args = parser.parse_args()
    build_bundle(args.output_dir)


if __name__ == '__main__':
    main()
