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
    ('icon.ico', '.'),
    ('ui/ds.dat', 'ui'),
    ('ui/轮询设定', 'ui/轮询设定'),
]

# 收集customtkinter主题文件
try:
    import customtkinter
    customtkinter_path = os.path.dirname(customtkinter.__file__)
    datas.append((os.path.join(customtkinter_path, "assets"), "customtkinter/assets"))
    print("Successfully collected customtkinter assets")
except ImportError:
    print("Warning: customtkinter not found.")

# 收集各个包的数据
# 'chromadb' is needed for the legacy project conversion feature.
packages_to_collect = [
    'chromadb',
    'sentence_transformers',
    'tokenizers',
    'transformers',
    'scipy',
    'sklearn',
    'keybert',
    'langchain',
    'langchain_core',
    'langchain_community',
    'openai',
    'anthropic',
    'httpx'
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

# 收集tiktoken数据文件
try:
    # 使用collect_data_files确保tiktoken的编码文件被包含
    tiktoken_datas = collect_data_files('tiktoken', include_py_files=True)
    all_datas.extend(tiktoken_datas)
    
    # 显式添加 tiktoken_ext 目录
    tiktoken_ext_datas = collect_data_files('tiktoken_ext', include_py_files=True)
    all_datas.extend(tiktoken_ext_datas)
    
    print("Successfully collected tiktoken and tiktoken_ext data")
except Exception as e:
    print(f"Warning: Error collecting tiktoken data: {e}")

# 合并所有数据文件
all_datas.extend(datas)

a = Analysis(
    ['main.py'],
    pathex=['d:\\book\\AI_NovelGenerator'],
    binaries=all_binaries,  # 使用收集到的binaries
    datas=all_datas,  # 使用合并后的all_datas
    hiddenimports=[
        *all_hiddenimports,  # 添加收集到的hiddenimports
        # The following are required for the legacy project conversion feature.
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
        'scipy.sparse',
        'scipy.sparse.csr',
        'scipy._cyutility',
        'sklearn',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors._typedefs',
        'sklearn.neighbors._quad_tree',
        'sklearn.tree',
        'sklearn.tree._utils',
        'sklearn.base',
        'sklearn.metrics',
        'sklearn.metrics.pairwise',
        'sklearn.preprocessing',
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'google.ai.generativelanguage',
        'nltk',
        'nltk.tokenize',
        'nltk.tokenize.punkt',
        'filelock',
        'packaging',
        'regex',
        'requests',
        'keybert',
        'tkcalendar',
        'langchain',
        'langchain_core',
        'langchain_openai',
        'langchain_community',
        'langchain_chroma', # Required for legacy project conversion.
        'openai',
        'azure.ai.inference',
        'httpx',
        'anthropic',
        'python-docx',
        'watchdog',
        'typing-extensions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'tkinter.test',
        'tornado',
        'IPython',
        'jupyter',
        'pytest',
    ],
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
    [],
    exclude_binaries=True,
    name='AI_NovelGenerator V1.7.3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='icon.ico'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI_NovelGenerator V1.7.3'
)
