#!/usr/bin/env python3

import sys
import csv
import os
from pathlib import Path
from datetime import datetime, timezone
import shutil
import json
import hashlib

# Credentials always live in ~/.cassn_credentials/ regardless of how the app is launched.
# When frozen (bundled .app): assets live in sys._MEIPASS.
# When running as a script: assets live next to the script.
_CONFIG_DIR = Path.home() / ".cassn_credentials"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
else:
    _BUNDLE_DIR = Path(__file__).parent
_LOCAL_DATA_DIR = Path(__file__).parent / "local_data"

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QComboBox, QDateEdit, QCheckBox,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout, QScrollArea,
    QCompleter, QFrame, QSizePolicy, QProgressBar
)
from PySide6.QtCore import Qt, QDate, QStringListModel, QThread, Signal
from PySide6.QtGui import QFont, QPixmap

# Box SDK
try:
    from box_sdk_gen import BoxClient, BoxOAuth, OAuthConfig
    BOX_AVAILABLE = True
except ImportError:
    BOX_AVAILABLE = False
    print("Warning: box-sdk-gen not available. Install with: pip install box-sdk-gen")

# EXIF handling
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    import piexif
    EXIF_AVAILABLE = True
except ImportError:
    EXIF_AVAILABLE = False
    print("Warning: PIL/piexif not available. Install with: pip install pillow piexif")

APP_TITLE = "CA-SSN Field Data Manager"
VERSION = "2.1"

# Load Box credentials from config.json
def load_box_config():
    """Load Box configuration from config.json"""
    config_path = _CONFIG_DIR / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Please copy config.json.example to config.json and add your Box credentials."
        )

    with open(config_path, 'r') as f:
        config = json.load(f)

    return (
        config['box']['client_id'],
        config['box']['client_secret'],
        config['box']['target_folder_id']
    )

try:
    BOX_CLIENT_ID, BOX_CLIENT_SECRET, BOX_TARGET_FOLDER_ID = load_box_config()
except FileNotFoundError as e:
    print(f"Warning: {e}")
    BOX_CLIENT_ID = BOX_CLIENT_SECRET = BOX_TARGET_FOLDER_ID = None

def _required_local_csv_path(filename):
    """Return the required repo-local CSV path."""
    return _LOCAL_DATA_DIR / filename


def load_reserves_from_csv():
    """Load reserves from local_data/sites.csv."""
    reserves = []
    csv_path = _required_local_csv_path("sites.csv")

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                site_code = row['site_code'].strip()
                site_name = row['site_name'].strip()
                if site_code and site_name:
                    reserves.append((site_code, site_name))
        if not reserves:
            raise ValueError(f"No site rows found in {csv_path}")
    except Exception as e:
        print(
            "Warning: Could not load site lookup data. "
            f"Expected {csv_path}. Copy example_data/sites.csv to local_data/sites.csv and edit it. Error: {e}"
        )
        reserves = []

    return reserves


def load_plot_names_from_csv():
    """Load plot names from local_data/plots.csv."""
    plot_names = {}
    plot_metadata = {}
    csv_path = _required_local_csv_path("plots.csv")

    try:
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        site_code = row['site_code'].strip()
                        plot_number = int(row['plot_number'])
                        plot_name = row['plot_name'].strip()
                        plot_latitude = row.get('plot_latitude', '').strip()
                        plot_longitude = row.get('plot_longitude', '').strip()
                        plot_description = row.get('plot_description', '').strip()

                        if site_code not in plot_names:
                            plot_names[site_code] = [None, None, None, None]

                        if 1 <= plot_number <= 4 and plot_name:
                            plot_names[site_code][plot_number - 1] = plot_name
                        plot_metadata[(site_code, plot_number)] = {
                            'plot_name': plot_name,
                            'plot_latitude': plot_latitude,
                            'plot_longitude': plot_longitude,
                            'plot_description': plot_description,
                        }
                break  # successfully read — stop trying encodings
            except UnicodeDecodeError:
                plot_names = {}
                plot_metadata = {}
                continue
    except Exception as e:
        print(
            "Warning: Could not load plot lookup data. "
            f"Expected {csv_path}. Copy example_data/plots.csv to local_data/plots.csv and edit it. Error: {e}"
        )
        plot_names = {}
        plot_metadata = {}

    return plot_names, plot_metadata


# Organization and reserve lists
ORGANIZATIONS = ["UC"]
RESERVES = load_reserves_from_csv()
PLOT_NAMES, PLOT_METADATA = load_plot_names_from_csv()

# Device type definitions
DEVICE_TYPES = {
    "ML": "Medium-Large Animal Camera",
    "SA": "Small Animal Camera",
    "BD": "Acoustic Recorder Birds",
    "BT": "Acoustic Recorder Bats",
}

# People list for data downloader
DOWNLOADERS = [
    "Bloom, Ryan",
    "Imperato, John",
    "Kaplan-Zenk, Samara",
    "Other"
]

# File type classification
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif', '.cr2', '.nef', '.arw', '.dng'}
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.aac', '.wma', '.ogg'}
CONFIG_EXTENSIONS = {'.txt'}


def classify_file(filename):
    """Classify file as image, audio, config, or other."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in AUDIO_EXTENSIONS:
        return "audio"
    elif ext in CONFIG_EXTENSIONS:
        return "config"
    else:
        return "other"


def extract_exif_data(image_path):
    """Extract EXIF data from image file"""
    if not EXIF_AVAILABLE:
        return {}
    
    try:
        img = Image.open(image_path)
        exif_data = {}
        
        if hasattr(img, '_getexif') and img._getexif():
            exif = img._getexif()
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                exif_data[tag] = value
        
        return exif_data
    except Exception as e:
        return {"error": str(e)}


def compute_file_hash(filepath):
    """Compute SHA-256 hash of file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_box_client():
    """Get authenticated Box client with automatic token refresh"""
    token_file = _CONFIG_DIR / "box_tokens.json"

    if not token_file.exists():
        return None
    
    try:
        # Simple custom token storage that works with our JSON format
        class SimpleTokenStorage:
            def __init__(self, token_file_path):
                self.token_file = token_file_path
                
            def store(self, token):
                """Store token - called automatically on refresh"""
                tokens = {
                    'access_token': token.access_token,
                    'refresh_token': token.refresh_token
                }
                with open(self.token_file, 'w') as f:
                    json.dump(tokens, f, indent=2)
            
            def get(self):
                """Get current token"""
                try:
                    with open(self.token_file, 'r') as f:
                        data = json.load(f)
                    # Return a token-like object
                    from box_sdk_gen import AccessToken
                    return AccessToken(
                        access_token=data['access_token'],
                        refresh_token=data.get('refresh_token')
                    )
                except:
                    return None
            
            def clear(self):
                """Clear tokens"""
                if self.token_file.exists():
                    self.token_file.unlink()
        
        # Create OAuth config with our custom storage
        config = OAuthConfig(
            client_id=BOX_CLIENT_ID,
            client_secret=BOX_CLIENT_SECRET,
            token_storage=SimpleTokenStorage(token_file)
        )
        
        # Create OAuth instance - it will load tokens from storage
        auth = BoxOAuth(config)
        
        # Create and return client - it will auto-refresh tokens as needed
        return BoxClient(auth)
        
    except Exception as e:
        print(f"Box authentication error: {e}")
        import traceback
        traceback.print_exc()
        return None


class BoxUploadThread(QThread):
    """Background thread for uploading files to Box"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, deployment_folder, metadata):
        super().__init__()
        self.deployment_folder = deployment_folder
        self.metadata = metadata
        self.client = None
    
    def run(self):
        """Upload deployment folder to Box"""
        try:
            self.client = get_box_client()
            if not self.client:
                self.finished.emit(False, "Could not authenticate with Box")
                return
            
            # Validate reserve name against canonical list before building path
            valid_names = {name for _, name in RESERVES}
            reserve_name = self.metadata.get('reserve_name', '')
            if reserve_name not in valid_names:
                self.finished.emit(
                    False,
                    f"Reserve name '{reserve_name}' not found in sites.csv. "
                    "Cannot determine Box folder path."
                )
                return

            # Build nested path: root → year → reserve → deployment
            TARGET_FOLDER_ID = BOX_TARGET_FOLDER_ID
            year = self.metadata['deployment_end'][:4]
            deploy_name = self.deployment_folder.name

            year_folder   = self.find_or_create_folder(self.client, TARGET_FOLDER_ID, year)
            site_folder   = self.find_or_create_folder(self.client, year_folder.id, reserve_name)
            deploy_folder = self.find_or_create_folder(self.client, site_folder.id, deploy_name)
            
            uploadable_files = [
                path for path in self.deployment_folder.rglob('*')
                if path.is_file() and self.should_upload_file(path)
            ]
            total_files = len(uploadable_files)
            uploaded = 0
            
            # Upload all files
            for file_path in uploadable_files:
                rel_path = file_path.relative_to(self.deployment_folder)
                self.upload_file_with_path(
                    file_path, deploy_folder.id, rel_path
                )
                uploaded += 1
                self.progress.emit(uploaded, total_files, file_path.name)
            
            self.finished.emit(True, f"Successfully uploaded {uploaded} files to Box")
            
        except Exception as e:
            self.finished.emit(False, f"Upload error: {str(e)}")

    @staticmethod
    def should_upload_file(file_path):
        """Skip macOS/Finder junk files from Box uploads."""
        name = file_path.name
        return not (name.startswith('.') or name.startswith('._'))
    
    def find_or_create_folder(self, client, parent_id, folder_name):
        """Find existing folder or create new one"""
        try:
            # Search for existing folder
            items = client.folders.get_folder_items(parent_id).entries
            for item in items:
                if item.type == 'folder' and item.name == folder_name:
                    return item
            
            # Create new folder - using proper CreateFolderParent format
            from box_sdk_gen import CreateFolderParent
            parent = CreateFolderParent(id=parent_id)
            new_folder = client.folders.create_folder(folder_name, parent)
            return new_folder
        except Exception as e:
            raise Exception(f"Error creating folder '{folder_name}': {e}")
    
    def upload_file_with_path(self, local_path, parent_folder_id, relative_path):
        """Upload file maintaining directory structure"""
        # Create any intermediate folders
        current_folder_id = parent_folder_id
        
        if len(relative_path.parts) > 1:
            for folder_name in relative_path.parts[:-1]:
                folder = self.find_or_create_folder(
                    self.client, current_folder_id, folder_name
                )
                current_folder_id = folder.id
        
        # Upload the file
        file_name = relative_path.name
        with open(local_path, 'rb') as file_stream:
            self.client.uploads.upload_file(
                attributes={'name': file_name, 'parent': {'id': current_folder_id}},
                file=file_stream
            )


class FieldDataWizard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(900, 700)
        
        # Data storage
        self.metadata = {}
        self.devices = []
        self.staging_root = Path.home() / "Desktop" / "CASSN_field_data_staging"
        self.current_deployment_folder = None
        self.file_inventory = []
        self.upload_thread = None
        
        # Load saved config
        self.config_file = Path.home() / ".cassn_credentials" / "config.json"
        self.load_config()

        # Load Wildlife Insights lookup tables
        self.wi_camera_metadata = self._load_wi_camera_metadata()
        self.wi_config = self._load_wi_config()

        # Check Box authentication
        self.box_authenticated = self.check_box_auth()
        
        # Build UI
        self.init_ui()
    
    def check_box_auth(self):
        """Check if Box is authenticated"""
        if not BOX_AVAILABLE:
            return False
        
        # Look for tokens next to .app (or script folder when not bundled)
        token_file = _CONFIG_DIR / "box_tokens.json"
        if not token_file.exists():
            return False
        
        try:
            client = get_box_client()
            if client:
                user = client.users.get_user_me()
                return True
        except:
            pass
        
        return False
    
    def load_config(self):
        """Load saved configuration"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    if 'staging_root' in config:
                        self.staging_root = Path(config['staging_root'])
        except:
            pass
    
    def save_config(self):
        """Save configuration"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump({'staging_root': str(self.staging_root)}, f)
        except:
            pass
    
    def init_ui(self):
        """Initialize the user interface"""
        # Set window icon
        icon_path = _BUNDLE_DIR / "assets" / "cassn_icon.png"
        if icon_path.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Logo banner at top - logo + title
        banner_layout = QHBoxLayout()
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.addStretch()

        # CA-SSN Logo
        cassn_logo_path = _BUNDLE_DIR / "assets" / "cassn_icon.png"
        if cassn_logo_path.exists():
            cassn_label = QLabel()
            cassn_pixmap = QPixmap(str(cassn_logo_path))
            cassn_scaled = cassn_pixmap.scaledToHeight(140, Qt.SmoothTransformation)
            cassn_label.setPixmap(cassn_scaled)
            cassn_label.setAlignment(Qt.AlignCenter)
            banner_layout.addWidget(cassn_label)

        banner_layout.addSpacing(10)

        # App title
        title_label = QLabel("CA-SSN Field Data Manager")
        title_font = QFont("Arial", 24, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        banner_layout.addWidget(title_label)

        banner_layout.addStretch()
        main_layout.addLayout(banner_layout)
        main_layout.addSpacing(10)
        
        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Create tabs
        self.create_metadata_tab()
        self.create_collection_tab()
        self.create_review_tab()
    
    def create_metadata_tab(self):
        """Create the deployment metadata entry tab"""
        tab = QWidget()
        self.tabs.addTab(tab, "1. Deployment Metadata")
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        
        # Title
        title = QLabel("Deployment Metadata")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # Form layout for metadata fields
        form_group = QGroupBox("Deployment Information")
        form_layout = QFormLayout()
        
        # Organization
        self.org_combo = QComboBox()
        self.org_combo.addItems(ORGANIZATIONS)
        form_layout.addRow("Organization:", self.org_combo)
        
        # Site (with autocomplete)
        self.reserve_combo = QComboBox()
        self.reserve_combo.setEditable(True)
        reserve_names = [name for code, name in RESERVES]
        self.reserve_combo.addItems(reserve_names)
        
        completer = QCompleter(reserve_names)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.reserve_combo.setCompleter(completer)
        self.reserve_combo.currentTextChanged.connect(self.on_reserve_changed)
        form_layout.addRow("Site:", self.reserve_combo)
        
        # Site code
        self.site_code_edit = QLineEdit()
        self.site_code_edit.setReadOnly(True)
        form_layout.addRow("Site Code:", self.site_code_edit)
        
        # Deployment dates
        self.deploy_start_date = QDateEdit()
        self.deploy_start_date.setCalendarPopup(True)
        self.deploy_start_date.setDate(QDate.currentDate())
        form_layout.addRow("Deployment Start Date:", self.deploy_start_date)
        
        self.deploy_end_date = QDateEdit()
        self.deploy_end_date.setCalendarPopup(True)
        self.deploy_end_date.setDate(QDate.currentDate())
        form_layout.addRow("Deployment End Date:", self.deploy_end_date)
        
        # Observer/Downloader
        self.observer_combo = QComboBox()
        self.observer_combo.setEditable(True)
        self.observer_combo.addItems(DOWNLOADERS)
        self.observer_combo.currentTextChanged.connect(self.on_observer_changed)
        form_layout.addRow("Who is downloading data?", self.observer_combo)
        
        # Other observer entry
        self.observer_other_edit = QLineEdit()
        self.observer_other_edit.setPlaceholderText("Enter name...")
        self.observer_other_edit.hide()
        form_layout.addRow("", self.observer_other_edit)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # Device selection
        device_group = QGroupBox("Select Devices for Each Plot")
        device_layout = QVBoxLayout()
        
        instructions = QLabel("Check which devices you are downloading data from.")
        device_layout.addWidget(instructions)
        
        # Device grid
        grid_layout = QGridLayout()
        
        grid_layout.addWidget(QLabel("Plot"), 0, 0)
        col = 1
        for dev_code, dev_name in DEVICE_TYPES.items():
            label = QLabel(dev_name)
            label.setWordWrap(True)
            grid_layout.addWidget(label, 0, col)
            col += 1
        
        self.device_checkboxes = {}
        self.plot_labels = {}
        
        for plot_num in range(1, 5):
            plot_label = QLabel(f"Plot {plot_num}")
            self.plot_labels[plot_num] = plot_label
            grid_layout.addWidget(plot_label, plot_num, 0)
            
            self.device_checkboxes[plot_num] = {}
            col = 1
            for dev_code in DEVICE_TYPES.keys():
                cb = QCheckBox()
                self.device_checkboxes[plot_num][dev_code] = cb
                grid_layout.addWidget(cb, plot_num, col, Qt.AlignCenter)
                col += 1
        
        device_layout.addLayout(grid_layout)
        
        # Quick select buttons
        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All Devices")
        select_all_btn.clicked.connect(self.select_all_devices)
        clear_all_btn = QPushButton("Clear All Devices")
        clear_all_btn.clicked.connect(self.clear_all_devices)
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(clear_all_btn)
        button_layout.addStretch()
        device_layout.addLayout(button_layout)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # Staging location
        staging_group = QGroupBox("Local Staging Location")
        staging_layout = QHBoxLayout()
        
        self.staging_label = QLineEdit(str(self.staging_root))
        self.staging_label.setReadOnly(True)
        staging_layout.addWidget(self.staging_label)
        
        change_btn = QPushButton("Change...")
        change_btn.clicked.connect(self.choose_staging_location)
        staging_layout.addWidget(change_btn)
        
        self.set_default_cb = QCheckBox("Set as default")
        staging_layout.addWidget(self.set_default_cb)
        
        staging_group.setLayout(staging_layout)
        layout.addWidget(staging_group)
        
        # Box upload option
        box_group = QGroupBox("Box Cloud Storage")
        box_layout = QVBoxLayout()
        
        # Box connection status indicator
        box_status_layout = QHBoxLayout()
        box_status_label = QLabel()
        if self.box_authenticated:
            box_status_label.setText("✓ Box Connected")
            box_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            box_status_label.setText("⚠ Box Not Connected")
            box_status_label.setStyleSheet("color: orange; font-weight: bold;")
        box_status_layout.addWidget(box_status_label)
        box_status_layout.addStretch()
        box_layout.addLayout(box_status_layout)
        
        self.upload_to_box_cb = QCheckBox("Upload to Box after processing")
        self.upload_to_box_cb.setChecked(self.box_authenticated)
        self.upload_to_box_cb.setEnabled(self.box_authenticated)
        box_layout.addWidget(self.upload_to_box_cb)
        
        if not self.box_authenticated:
            auth_note = QLabel("⚠ Box not connected. Run box_auth_setup.py to authenticate.")
            auth_note.setStyleSheet("color: orange;")
            box_layout.addWidget(auth_note)
        
        box_group.setLayout(box_layout)
        layout.addWidget(box_group)
        
        # Navigation button
        nav_layout = QHBoxLayout()
        nav_layout.addStretch()
        next_btn = QPushButton("Next: Collect SD Card Data →")
        next_btn.clicked.connect(self.validate_and_next)
        nav_layout.addWidget(next_btn)
        layout.addLayout(nav_layout)
        
        layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
    
    def create_collection_tab(self):
        """Create the SD card data collection tab"""
        tab = QWidget()
        self.tabs.addTab(tab, "2. Collect SD Card Data")
        
        layout = QVBoxLayout(tab)
        
        # Title
        title = QLabel("SD Card Data Collection")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        instructions = QLabel(
            "Insert SD card for each device, select it below, and click 'Copy Files'.\n"
            "Files will be automatically renamed and organized in the staging folder."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Device tree
        device_group = QGroupBox("Devices")
        device_layout = QVBoxLayout()
        
        self.device_tree = QTreeWidget()
        self.device_tree.setHeaderLabels(["Plot", "Device Type", "Status", "Files Copied"])
        self.device_tree.setColumnWidth(0, 150)
        self.device_tree.setColumnWidth(1, 200)
        self.device_tree.setColumnWidth(2, 100)
        device_layout.addWidget(self.device_tree)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        copy_btn = QPushButton("Select SD Card && Copy Files")
        copy_btn.clicked.connect(self.copy_sd_card_data)
        skip_btn = QPushButton("Skip Selected Device")
        skip_btn.clicked.connect(self.skip_device)
        control_layout.addWidget(copy_btn)
        control_layout.addWidget(skip_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # Progress log
        log_group = QGroupBox("Progress Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Navigation
        nav_layout = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        next_btn = QPushButton("Next: Review && Finalize →")
        next_btn.clicked.connect(self.validate_and_next_collection)
        nav_layout.addWidget(back_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(next_btn)
        layout.addLayout(nav_layout)
    
    def create_review_tab(self):
        """Create the review and finalize tab"""
        tab = QWidget()
        self.tabs.addTab(tab, "3. Review & Finalize")
        
        layout = QVBoxLayout(tab)
        
        # Title
        title = QLabel("Deployment Summary")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # Summary text
        summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout()
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        summary_layout.addWidget(self.summary_text)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        # Upload progress (hidden by default)
        self.upload_group = QGroupBox("Box Upload Progress")
        upload_layout = QVBoxLayout()
        
        self.upload_progress_bar = QProgressBar()
        self.upload_progress_bar.setMinimum(0)
        self.upload_progress_bar.setMaximum(100)
        upload_layout.addWidget(self.upload_progress_bar)
        
        self.upload_status_label = QLabel("")
        upload_layout.addWidget(self.upload_status_label)
        
        self.upload_group.setLayout(upload_layout)
        self.upload_group.hide()
        layout.addWidget(self.upload_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.open_btn = QPushButton("Open Staging Folder")
        self.open_btn.clicked.connect(self.open_staging_folder)
        
        self.upload_now_btn = QPushButton("Upload to Box Now")
        self.upload_now_btn.clicked.connect(self.upload_to_box_manual)
        self.upload_now_btn.setEnabled(self.box_authenticated)
        
        self.new_btn = QPushButton("Start New Deployment")
        self.new_btn.clicked.connect(self.start_new_deployment)
        
        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.open_btn)
        button_layout.addWidget(self.upload_now_btn)
        button_layout.addWidget(self.new_btn)
        button_layout.addStretch()
        button_layout.addWidget(exit_btn)
        layout.addLayout(button_layout)
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def on_reserve_changed(self, text):
        """Update site code and plot names when reserve changes"""
        for code, name in RESERVES:
            if name == text:
                self.site_code_edit.setText(code)
                self.update_plot_labels(code)
                return
        self.site_code_edit.setText("")
    
    def on_observer_changed(self, text):
        """Show/hide other observer entry"""
        if text == "Other":
            self.observer_other_edit.show()
        else:
            self.observer_other_edit.hide()
    
    def update_plot_labels(self, reserve_code):
        """Update plot labels based on reserve"""
        plot_names = PLOT_NAMES.get(reserve_code, None)
        
        for plot_num in range(1, 5):
            if plot_names and len(plot_names) >= plot_num:
                self.plot_labels[plot_num].setText(f"Plot {plot_num}: {plot_names[plot_num - 1]}")
            else:
                self.plot_labels[plot_num].setText(f"Plot {plot_num}")
    
    def select_all_devices(self):
        """Select all device checkboxes"""
        for plot_num in range(1, 5):
            for dev_code in DEVICE_TYPES.keys():
                self.device_checkboxes[plot_num][dev_code].setChecked(True)
    
    def clear_all_devices(self):
        """Clear all device checkboxes"""
        for plot_num in range(1, 5):
            for dev_code in DEVICE_TYPES.keys():
                self.device_checkboxes[plot_num][dev_code].setChecked(False)
    
    def choose_staging_location(self):
        """Choose staging directory"""
        directory = QFileDialog.getExistingDirectory(
            self, "Choose Staging Location", str(self.staging_root)
        )
        if directory:
            self.staging_root = Path(directory)
            self.staging_label.setText(str(self.staging_root))
    
    def validate_and_next(self):
        """Validate metadata and proceed to collection tab"""
        # Validation
        if not self.reserve_combo.currentText():
            QMessageBox.warning(self, "Missing Information", "Please select a site.")
            return
        
        if not self.site_code_edit.text():
            QMessageBox.warning(self, "Missing Information", "Please select a valid site.")
            return
        
        observer = self.observer_combo.currentText()
        if not observer:
            QMessageBox.warning(self, "Missing Information", "Please select who is downloading data.")
            return
        
        if observer == "Other" and not self.observer_other_edit.text().strip():
            QMessageBox.warning(self, "Missing Information", "Please enter a name for 'Other' option.")
            return
        
        # Store metadata
        reserve_name = self.reserve_combo.currentText()
        reserve_code = self.site_code_edit.text()
        
        self.metadata = {
            'organization': self.org_combo.currentText(),
            'reserve_name': reserve_name,
            'site': reserve_code,
            'deployment_start': self.deploy_start_date.date().toString("yyyy-MM-dd"),
            'deployment_end': self.deploy_end_date.date().toString("yyyy-MM-dd"),
            'observer': self.observer_other_edit.text() if observer == "Other" else observer,
        }
        
        # Build device list
        plot_names = PLOT_NAMES.get(reserve_code, None)
        
        self.devices = []
        for plot_num in range(1, 5):
            if plot_names and len(plot_names) >= plot_num:
                plot_label = plot_names[plot_num - 1]
            else:
                plot_label = str(plot_num)
            
            for dev_code in DEVICE_TYPES.keys():
                if self.device_checkboxes[plot_num][dev_code].isChecked():
                    device_label = f"p{plot_num}_{dev_code}"
                    self.devices.append((plot_num, plot_label, dev_code, device_label))
        
        if not self.devices:
            QMessageBox.warning(self, "No Devices Selected", "Please select at least one device.")
            return
        
        # Save config if requested
        if self.set_default_cb.isChecked():
            self.save_config()
        
        # Create deployment folder
        self.create_deployment_folder()
        
        # Populate collection list
        self.populate_collection_list()
        
        # Go to collection tab
        self.tabs.setCurrentIndex(1)
    
    def create_deployment_folder(self):
        """Create deployment folder in staging location based on deployment end date"""
        folder_name = f"{self.metadata['organization']}_{self.metadata['site']}_{self.metadata['deployment_end'].replace('-', '')}"

        self.current_deployment_folder = self.staging_root / folder_name
        self.current_deployment_folder.mkdir(parents=True, exist_ok=True)
        
        (self.current_deployment_folder / "raw_data").mkdir(exist_ok=True)
        
        metadata_file = self.current_deployment_folder / "deployment_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def populate_collection_list(self):
        """Populate device tree with selected devices"""
        self.device_tree.clear()
        
        for plot_num, plot_label, dev_code, device_label in self.devices:
            item = QTreeWidgetItem([
                f"Plot {plot_num} ({plot_label})",
                DEVICE_TYPES[dev_code],
                "Pending",
                "0"
            ])
            self.device_tree.addTopLevelItem(item)
    
    def log(self, message):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        QApplication.processEvents()
    
    def copy_sd_card_data(self):
        """Copy data from SD card for selected device"""
        selected = self.device_tree.currentItem()
        if not selected:
            QMessageBox.information(self, "No Selection", "Please select a device from the list.")
            return
        
        index = self.device_tree.indexOfTopLevelItem(selected)
        plot_num, plot_label, dev_code, device_label = self.devices[index]
        
        # Check if already complete
        if selected.text(2) == "Complete":
            reply = QMessageBox.question(
                self, "Already Complete",
                "This device is already complete. Copy again?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # Select SD card
        sd_path = QFileDialog.getExistingDirectory(
            self, f"Select SD Card for Plot {plot_num} - {DEVICE_TYPES[dev_code]}"
        )
        
        if not sd_path:
            return
        
        self.log(f"Starting copy for Plot {plot_num} ({plot_label}) - {DEVICE_TYPES[dev_code]}...")
        self.log(f"Source: {sd_path}")
        
        # Create device folder
        device_folder = self.current_deployment_folder / "raw_data" / device_label
        device_folder.mkdir(parents=True, exist_ok=True)
        
        try:
            files_copied = self.process_sd_card_files(
                Path(sd_path), device_folder, plot_num, plot_label, dev_code, device_label
            )
            
            selected.setText(2, "Complete")
            selected.setText(3, str(files_copied))
            
            self.log(f"✓ Completed! {files_copied} files copied.\n")
            
        except Exception as e:
            self.log(f"✗ Error: {str(e)}\n")
            QMessageBox.critical(self, "Copy Error", f"Error copying files: {str(e)}")
    
    def process_sd_card_files(self, source_dir, dest_dir, plot_num, plot_label, dev_code, device_label):
        """Process files from SD card."""
        files_copied = 0
        file_sequence = 1

        # Deployment end date for media filenames (YYYYMM)
        deploy_date = datetime.strptime(self.metadata['deployment_end'], "%Y-%m-%d")
        date_str = deploy_date.strftime("%Y%m")

        # Deployment start date for config filenames (YYYYMMDD)
        deploy_start = datetime.strptime(self.metadata['deployment_start'], "%Y-%m-%d")
        start_date_str = deploy_start.strftime("%Y%m%d")

        org = self.metadata['organization']
        site = self.metadata['site']
        plot_metadata = PLOT_METADATA.get((site, plot_num), {})

        for root, dirs, files in os.walk(source_dir):
            for filename in files:
                if filename.startswith('.') or filename.startswith('_'):
                    continue

                source_path = Path(root) / filename
                file_ext = source_path.suffix.lower()
                file_type = classify_file(filename)

                if file_type == "other":
                    continue

                if file_type == "config":
                    # Rename: ORG_SITE_DEVCODE_YYYYMMDD_CONFIG_01.txt
                    new_filename = f"{org}_{site}_{dev_code}_{start_date_str}_CONFIG_01{file_ext}"
                    dest_path = dest_dir / new_filename
                else:
                    # Media files: standard rename convention
                    seq_str = f"{file_sequence:05d}"
                    new_filename = f"{org}_{site}_plot{plot_num}_{dev_code}_{date_str}_{seq_str}{file_ext}"
                    dest_path = dest_dir / new_filename
                    file_sequence += 1

                shutil.copy2(source_path, dest_path)

                exif_data = {}
                if file_type == "image" and EXIF_AVAILABLE:
                    exif_data = extract_exif_data(dest_path)

                file_hash = compute_file_hash(dest_path)

                file_info = {
                    'original_filename': filename,
                    'new_filename': new_filename,
                    'plot_number': plot_num,
                    'plot_label': plot_label,
                    'device_type': dev_code,
                    'device_label': device_label,
                    'file_type': file_type,
                    'file_size_bytes': dest_path.stat().st_size,
                    'file_hash_sha256': file_hash,
                    'source_path': str(source_path),
                    'timestamp': datetime.fromtimestamp(dest_path.stat().st_mtime).isoformat(),
                    'latitude': plot_metadata.get('plot_latitude') or '',
                    'longitude': plot_metadata.get('plot_longitude') or '',
                    'exif_datetime': exif_data.get('DateTime'),
                    'exif_make': exif_data.get('Make'),
                    'exif_model': exif_data.get('Model'),
                }

                self.file_inventory.append(file_info)
                files_copied += 1

                if files_copied % 50 == 0:
                    self.log(f"  ...{files_copied} files processed")

        return files_copied
    
    def skip_device(self):
        """Skip selected device"""
        selected = self.device_tree.currentItem()
        if not selected:
            QMessageBox.information(self, "No Selection", "Please select a device from the list.")
            return
        
        index = self.device_tree.indexOfTopLevelItem(selected)
        plot_num, plot_label, dev_code, device_label = self.devices[index]
        
        selected.setText(2, "Skipped")
        selected.setText(3, "0")
        
        self.log(f"Skipped Plot {plot_num} - {DEVICE_TYPES[dev_code]}\n")
    
    def validate_and_next_collection(self):
        """Validate collection and proceed to review"""
        pending = False
        for i in range(self.device_tree.topLevelItemCount()):
            item = self.device_tree.topLevelItem(i)
            if item.text(2) == "Pending":
                pending = True
                break
        
        if pending:
            reply = QMessageBox.question(
                self, "Incomplete Collection",
                "Some devices are still pending. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.generate_metadata_files()
        self.update_review_tab()
        self.tabs.setCurrentIndex(2)
        
        # Auto-upload if enabled
        if self.upload_to_box_cb.isChecked() and self.box_authenticated:
            self.upload_to_box()
    
    def generate_metadata_files(self):
        """Generate CSV and JSON metadata files"""
        csv_path = self.current_deployment_folder / "file_metadata.csv"
        
        csv_fields = [
            'new_filename', 'original_filename', 'plot_number', 'plot_label',
            'device_type', 'device_label', 'file_type', 'file_size_bytes',
            'file_hash_sha256', 'timestamp', 'latitude', 'longitude',
            'exif_datetime', 'exif_make', 'exif_model', 'source_path'
        ]
        
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(self.file_inventory)
        
        self.log(f"Generated: file_metadata.csv ({len(self.file_inventory)} files)")
        
        manifest = {
            'deployment_info': self.metadata,
            'devices': [
                {
                    'plot_number': pn,
                    'plot_label': pl,
                    'device_type': dc,
                    'device_label': dl
                }
                for pn, pl, dc, dl in self.devices
            ],
            'file_count': len(self.file_inventory),
            'generated': datetime.now().isoformat(),
            'version': VERSION
        }
        
        manifest_path = self.current_deployment_folder / "manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        self.log(f"Generated: manifest.json")

        self._wi_status_lines = self.generate_wi_deployments()
    
    # ------------------------------------------------------------------
    # Wildlife Insights helpers
    # ------------------------------------------------------------------

    def _load_wi_camera_metadata(self) -> dict:
        """Load local_data/cameras.csv → dict keyed (site_code, plot_number_int, device_type)."""
        path = _LOCAL_DATA_DIR / "cameras.csv"
        if not path.exists():
            return {}
        result = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        key = (row["site_code"].strip(), int(row["plot_number"]), row["device_type"].strip())
                        result[key] = row
                    except (KeyError, ValueError):
                        continue
        except Exception as e:
            self.log(f"Warning: could not load cameras.csv: {e}")
        return result

    def _load_wi_config(self) -> dict:
        """Load local_data/wi_config.json."""
        path = _LOCAL_DATA_DIR / "wi_config.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.log(f"Warning: could not load wi_config.json: {e}")
            return {}

    def _load_wi_plot_coords(self) -> dict:
        """Load local_data/plots.csv → dict keyed (site_code, plot_number_int)."""
        path = _LOCAL_DATA_DIR / "plots.csv"
        if not path.exists():
            return {}
        result = {}
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    for row in csv.DictReader(f):
                        try:
                            key = (row["site_code"].strip(), int(row["plot_number"]))
                            result[key] = {
                                "latitude": row.get("plot_latitude", "").strip(),
                                "longitude": row.get("plot_longitude", "").strip(),
                            }
                        except (KeyError, ValueError):
                            continue
                return result
            except UnicodeDecodeError:
                result = {}
        return result

    def generate_wi_deployments(self) -> list[str]:
        """Generate Wildlife Insights deployment CSVs into WI_metadata/ subfolder.

        Returns a list of status strings for the review tab.
        """
        WI_COLUMNS = [
            "project_id", "deployment_id", "subproject_name", "subproject_design",
            "placename", "longitude", "latitude", "start_date", "end_date",
            "event_name", "event_description", "event_type", "bait_type", "bait_description",
            "feature_type", "feature_type_methodology", "camera_id", "quiet_period",
            "camera_functioning", "sensor_height", "height_other", "sensor_orientation",
            "orientation_other", "recorded_by", "plot_treatment", "plot_treatment_description",
            "detection_distance",
        ]
        CAMERA_DEVICE_TYPES = {"ML", "SA"}

        status_lines = []

        if not self.wi_config:
            msg = "Skipping Wildlife Insights export: wi_config.json not found in local_data/"
            self.log(msg)
            status_lines.append(msg)
            return status_lines

        plot_coords = self._load_wi_plot_coords()

        site = self.metadata.get("site", "")
        org = self.metadata.get("organization", "")
        start = self.metadata.get("deployment_start", "")
        end = self.metadata.get("deployment_end", "")
        observer = self.metadata.get("observer", "")
        subproject_name = f"{org}_{site}_{end.replace('-', '')}"

        try:
            from datetime import datetime as _dt
            s = _dt.strptime(start, "%Y-%m-%d")
            e = _dt.strptime(end, "%Y-%m-%d")
            event_name = f"{s.strftime('%Y%b').upper()}-{e.strftime('%Y%b').upper()}"
        except Exception:
            event_name = ""

        rows_by_type: dict[str, list[dict]] = {}

        for plot_num, _plot_label, dev_type, _dev_label in self.devices:
            if dev_type not in CAMERA_DEVICE_TYPES:
                continue
            try:
                plot_num_int = int(plot_num)
            except (TypeError, ValueError):
                plot_num_int = None

            cam = self.wi_camera_metadata.get((site, plot_num_int, dev_type), {}) if plot_num_int else {}
            coords = plot_coords.get((site, plot_num_int), {}) if plot_num_int else {}

            camera_id = cam.get("camera_id", "")
            if not camera_id:
                self.log(f"  WI Warning: camera_id missing for {site} plot {plot_num} {dev_type}")

            row = {
                "project_id": self.wi_config.get(f"project_id_{dev_type}", ""),
                "deployment_id": f"{org}_{site}_plot{plot_num}_{dev_type}_{end.replace('-', '')}",
                "subproject_name": subproject_name,
                "subproject_design": "",
                "placename": f"{site}_plot{plot_num}",
                "longitude": coords.get("longitude", ""),
                "latitude": coords.get("latitude", ""),
                "start_date": f"{start} 00:00:00" if start else "",
                "end_date": f"{end} 23:59:59" if end else "",
                "event_name": event_name,
                "event_description": "",
                "event_type": self.wi_config.get("event_type", "Temporal"),
                "bait_type": self.wi_config.get(f"bait_type_{dev_type}", ""),
                "bait_description": self.wi_config.get(f"bait_description_{dev_type}", ""),
                "feature_type": cam.get("feature_type", ""),
                "feature_type_methodology": "",
                "camera_id": camera_id,
                "quiet_period": self.wi_config.get("quiet_period", 0),
                "camera_functioning": self.wi_config.get("camera_functioning_default", "Camera Functioning"),
                "sensor_height": cam.get("sensor_height", "Knee height"),
                "height_other": "",
                "sensor_orientation": cam.get(
                    "sensor_orientation",
                    "Parallel" if dev_type == "ML" else "Pointed Downward"
                ),
                "orientation_other": "",
                "recorded_by": observer,
                "plot_treatment": "",
                "plot_treatment_description": "",
                "detection_distance": "",
            }
            rows_by_type.setdefault(dev_type, []).append(row)

        wi_dir = self.current_deployment_folder / "WI_metadata"
        wi_dir.mkdir(exist_ok=True)

        for dev_type in sorted(rows_by_type):
            rows = rows_by_type[dev_type]
            filename = f"wildlife_insights_{dev_type}_deployments.csv"
            out_path = wi_dir / filename
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=WI_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            msg = f"Generated: WI_metadata/{filename} ({len(rows)} rows)"
            self.log(msg)
            status_lines.append(f"  - {filename} ({len(rows)} rows)")

        return status_lines

    def update_review_tab(self):
        """Update review summary"""
        summary = []
        summary.append("=" * 60)
        summary.append("DEPLOYMENT SUMMARY")
        summary.append("=" * 60)
        summary.append("")
        
        summary.append("DEPLOYMENT INFORMATION")
        summary.append("-" * 60)
        summary.append(f"Organization: {self.metadata['organization']}")
        summary.append(f"Reserve: {self.metadata['reserve_name']}")
        summary.append(f"Site: {self.metadata['site']}")
        summary.append(f"Deployment Period: {self.metadata['deployment_start']} to {self.metadata['deployment_end']}")
        summary.append(f"Observer: {self.metadata['observer']}")
        summary.append("")
        
        summary.append("DEVICES COLLECTED")
        summary.append("-" * 60)
        for plot_num, plot_label, dev_code, device_label in self.devices:
            device_files = [f for f in self.file_inventory if f['device_label'] == device_label]
            summary.append(f"  Plot {plot_num} ({plot_label}) - {DEVICE_TYPES[dev_code]}: {len(device_files)} files")
        summary.append("")
        
        summary.append("FILES PROCESSED")
        summary.append("-" * 60)
        total_files = len(self.file_inventory)
        total_size = sum(f['file_size_bytes'] for f in self.file_inventory)
        total_size_mb = total_size / (1024 * 1024)
        
        summary.append(f"Total Files: {total_files}")
        summary.append(f"Total Size: {total_size_mb:.2f} MB")
        summary.append("")
        
        file_types = {}
        for f in self.file_inventory:
            ftype = f['file_type']
            file_types[ftype] = file_types.get(ftype, 0) + 1
        
        summary.append("File Types:")
        for ftype, count in file_types.items():
            summary.append(f"  {ftype}: {count}")
        summary.append("")
        
        summary.append("OUTPUT LOCATION")
        summary.append("-" * 60)
        summary.append(f"Local Staging: {self.current_deployment_folder}")
        summary.append("")
        summary.append("Files generated:")
        summary.append("  - deployment_metadata.json")
        summary.append("  - manifest.json")
        summary.append("  - file_metadata.csv")
        summary.append(f"  - raw_data/ ({total_files} files in device subfolders)")
        summary.append("")

        summary.append("WILDLIFE INSIGHTS")
        summary.append("-" * 60)
        wi_lines = getattr(self, "_wi_status_lines", [])
        if wi_lines:
            for line in wi_lines:
                summary.append(line)
        else:
            summary.append("  Skipped (wi_config.json not found in local_data/)")
        summary.append("")

        if self.upload_to_box_cb.isChecked():
            summary.append("Box Upload: In progress or will be uploaded...")
        
        summary.append("")
        summary.append("=" * 60)
        summary.append("NEXT STEPS")
        summary.append("=" * 60)
        summary.append("1. Review the files in the staging folder")
        summary.append("2. Verify Box upload completed successfully")
        summary.append("3. Keep a backup of the original SD cards until transfer is verified")
        
        self.summary_text.setText('\n'.join(summary))
    
    def upload_to_box(self):
        """Upload deployment folder to Box"""
        if not self.box_authenticated:
            QMessageBox.warning(self, "Box Not Connected", "Please authenticate with Box first.")
            return
        
        self.upload_group.show()
        self.upload_status_label.setText("Starting upload to Box...")
        self.upload_progress_bar.setValue(0)
        
        # Disable buttons during upload
        self.open_btn.setEnabled(False)
        self.upload_now_btn.setEnabled(False)
        self.new_btn.setEnabled(False)
        
        # Start upload thread
        self.upload_thread = BoxUploadThread(
            self.current_deployment_folder,
            self.metadata
        )
        self.upload_thread.progress.connect(self.on_upload_progress)
        self.upload_thread.finished.connect(self.on_upload_finished)
        self.upload_thread.start()
    
    def upload_to_box_manual(self):
        """Manual Box upload trigger"""
        if not self.current_deployment_folder:
            QMessageBox.information(self, "No Data", "No deployment data to upload.")
            return
        
        self.upload_to_box()
    
    def on_upload_progress(self, current, total, filename):
        """Update upload progress"""
        percent = int((current / total) * 100)
        self.upload_progress_bar.setValue(percent)
        self.upload_status_label.setText(f"Uploading: {filename} ({current}/{total})")
    
    def on_upload_finished(self, success, message):
        """Handle upload completion"""
        # Re-enable buttons
        self.open_btn.setEnabled(True)
        self.upload_now_btn.setEnabled(True)
        self.new_btn.setEnabled(True)
        
        if success:
            self.upload_progress_bar.setValue(100)
            self.upload_status_label.setText(f"✓ {message}")
            self.upload_status_label.setStyleSheet("color: green; font-weight: bold;")
            QMessageBox.information(self, "Upload Complete", message)
        else:
            self.upload_status_label.setText(f"✗ {message}")
            self.upload_status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.warning(self, "Upload Failed", message)
    
    def open_staging_folder(self):
        """Open staging folder in file explorer"""
        import subprocess
        import platform
        
        if platform.system() == 'Darwin':
            subprocess.run(['open', str(self.current_deployment_folder)])
        elif platform.system() == 'Windows':
            subprocess.run(['explorer', str(self.current_deployment_folder)])
        else:
            subprocess.run(['xdg-open', str(self.current_deployment_folder)])
    
    def start_new_deployment(self):
        """Reset for new deployment"""
        reply = QMessageBox.question(
            self, "Start New Deployment",
            "This will reset the wizard. Are you sure?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.metadata = {}
            self.devices = []
            self.file_inventory = []
            self.current_deployment_folder = None
            
            # Reset UI
            self.reserve_combo.setCurrentIndex(-1)
            self.site_code_edit.clear()
            self.deploy_start_date.setDate(QDate.currentDate())
            self.deploy_end_date.setDate(QDate.currentDate())
            self.observer_combo.setCurrentIndex(-1)
            self.clear_all_devices()
            self.device_tree.clear()
            self.log_text.clear()
            self.summary_text.clear()
            self.upload_group.hide()
            
            self.tabs.setCurrentIndex(0)


def main():
    if not EXIF_AVAILABLE:
        print("Warning: PIL/piexif not available. EXIF extraction will be disabled.")
        print("Install with: pip install pillow piexif")
    
    if not BOX_AVAILABLE:
        print("Warning: box-sdk-gen not available. Box upload will be disabled.")
        print("Install with: pip install box-sdk-gen")
        print("Then run box_auth_setup.py to authenticate")
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = FieldDataWizard()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
