# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.hooks import get_module_file_attribute
from PyInstaller.building.datastruct import Tree

def get_site_packages():
    """获取当前虚拟环境的site-packages路径"""
    venv_path = os.path.dirname(os.path.dirname(sys.executable))
    if os.path.exists(os.path.join(venv_path, 'Lib', 'site-packages')):
        return os.path.join(venv_path, 'Lib', 'site-packages')
    import site
    return site.getsitepackages()[0]

block_cipher = None

# 获取site-packages路径
site_packages = get_site_packages()
print(f"Found site-packages at: {site_packages}")

# 修改收集方法
def collect_package_data(package_name):
    datas = []
    binaries = []
    hiddenimports = []
    try:
        # 收集所有相关文件
        package_data = collect_all(package_name)
        datas.extend(package_data[0])
        binaries.extend(package_data[1])
        hiddenimports.extend(package_data[2])
        print(f"Successfully collected {package_name} data")
    except Exception as e:
        print(f"Warning: Error collecting {package_name} data: {e}")
    return datas, binaries, hiddenimports

# 收集基础文件
datas = [
    ('config.json', '.'),
    ('LICENSE', '.'),
    ('requirements.txt', '.'),
    ('README.md', '.'),
]

# 收集各个包的数据
packages_to_collect = [
    'chromadb',
    'sentence_transformers',
    'tokenizers',
    'transformers'
]

all_datas = []
all_binaries = []
all_hiddenimports = []

for package in packages_to_collect:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_package_data(package)
    all_datas.extend(pkg_datas)
    all_binaries.extend(pkg_binaries)
    all_hiddenimports.extend(pkg_hiddenimports)

# 修复NLTK数据收集
try:
    import nltk
    nltk.download('punkt', quiet=True)
    nltk_data_path = nltk.data.path[0]
    if os.path.exists(nltk_data_path):
        print(f"Found NLTK data at: {nltk_data_path}")
        # 修改这里的数据收集方式
        tokenizers_path = os.path.join(nltk_data_path, 'tokenizers')
        if os.path.exists(tokenizers_path):
            datas.append((tokenizers_path, 'nltk_data/tokenizers'))
except Exception as e:
    print(f"Warning: Unable to collect NLTK data: {e}")

# 添加einops依赖
try:
    import einops
    einops_path = os.path.dirname(einops.__file__)
    datas.append((einops_path, 'einops'))
except ImportError:
    print("Warning: einops not found, installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "einops"])

# 合并所有数据文件
all_datas.extend(datas)

a = Analysis(
    ['main.py'],
    pathex=['d:\\book\\AI_NovelGenerator'],
    binaries=all_binaries,  # 使用收集到的binaries
    datas=all_datas,  # 使用合并后的all_datas
    hiddenimports=[
        *all_hiddenimports,  # 添加收集到的hiddenimports
        'chromadb',
        'chromadb.api',
        'chromadb.api.models',
        'chromadb.api.types',
        'chromadb.config',
        'chromadb.db',
        'chromadb.utils',
        'hnswlib',
        'numpy',
        'sentence_transformers',
        'sentence_transformers.models',
        'transformers',
        'tokenizers',
        'tqdm',
        'scipy',
        'sklearn',
        'sklearn.metrics',
        'sklearn.metrics.pairwise',
        'customtkinter',
        'PIL',
        'google.generativeai',
        'nltk',
        'nltk.tokenize',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AI_NovelGenerator V1.5.2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'
)
