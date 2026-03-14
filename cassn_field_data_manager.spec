# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['cassn_field_data_manager.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('data', 'data'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CASSN Field Data Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CASSN Field Data Manager',
)

app = BUNDLE(
    coll,
    name='CASSN Field Data Manager.app',
    icon='assets/cassn_icon.icns',
    bundle_identifier='edu.ucnrs.cassn-field-data-manager',
    info_plist={
        'CFBundleShortVersionString': '2.1',
        'CFBundleVersion': '2.1',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
    },
)
