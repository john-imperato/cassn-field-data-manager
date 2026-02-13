from box_sdk_gen import BoxClient, BoxDeveloperTokenAuth
from box_sdk_gen import BoxOAuth, OAuthConfig
import json
import webbrowser
from pathlib import Path

# Load credentials from config.json
def load_box_config():
    """Load Box configuration from config.json"""
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Please copy config.json.example to config.json and add your Box credentials."
        )

    with open(config_path, 'r') as f:
        config = json.load(f)

    return config['box']['client_id'], config['box']['client_secret']

try:
    CLIENT_ID, CLIENT_SECRET = load_box_config()
except FileNotFoundError as e:
    print(f"Error: {e}")
    exit(1)

# Store tokens in same folder as script
TOKEN_FILE = Path(__file__).parent / 'box_tokens.json'

def store_tokens(access_token, refresh_token):
    """Save tokens to file"""
    tokens = {
        'access_token': access_token,
        'refresh_token': refresh_token
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)
    print(f"✓ Tokens saved to {TOKEN_FILE}")

def load_tokens():
    """Load tokens from file"""
    try:
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# Check if we already have tokens
existing_tokens = load_tokens()

if existing_tokens:
    print(f"✓ Found existing tokens in {TOKEN_FILE}")
    print("Testing connection...")
    
    try:
        # Use the access token directly
        auth = BoxDeveloperTokenAuth(token=existing_tokens['access_token'])
        client = BoxClient(auth)
        user = client.users.get_user_me()
        
        print(f"✓ Connected as: {user.name} ({user.login})")
        print("You're already authenticated!")
    except Exception as e:
        print(f"✗ Error testing connection: {e}")
        print("Re-authenticating with fresh tokens...")
        existing_tokens = None

if not existing_tokens:
    print("=" * 70)
    print("BOX AUTHENTICATION SETUP")
    print("=" * 70)
    
    config = OAuthConfig(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    
    auth = BoxOAuth(config)
    
    # Get authorization URL
    auth_url = auth.get_authorize_url()
    
    print("\n1. Opening your browser to authenticate with Box...")
    print(f"\nIf your browser doesn't open, go to this URL:")
    print(f"\n{auth_url}\n")
    
    # Try to open browser automatically
    try:
        webbrowser.open(auth_url)
    except:
        pass
    
    print("2. Log in to Box and click 'Grant access to Box'")
    print("3. Your browser will redirect to a page that won't load (that's normal!)")
    print("4. Copy the ENTIRE URL from your browser's address bar")
    print("5. Paste it below\n")
    print("=" * 70)
    
    redirect_response = input("\nPaste the full redirect URL here: ").strip()
    
    # Extract the authorization code from the URL
    try:
        auth_code = redirect_response.split('code=')[1].split('&')[0]
        print("\n✓ Authorization code extracted")
        
        # Exchange code for tokens
        print("✓ Exchanging code for tokens...")
        
        # Get tokens using the authorization code
        token_info = auth.get_tokens_authorization_code_grant(auth_code)
        
        # Save tokens
        store_tokens(token_info.access_token, token_info.refresh_token)
        
        print("✓ Authentication successful!")
        
        # Test the connection
        test_auth = BoxDeveloperTokenAuth(token=token_info.access_token)
        client = BoxClient(test_auth)
        user = client.users.get_user_me()
        
        print(f"\n{'=' * 70}")
        print(f"Connected to Box as: {user.name} ({user.login})")
        print(f"{'=' * 70}")
        print(f"\n✓ You're all set! Your tokens are saved in {TOKEN_FILE}")
        print("✓ You can now use Box in your Field Data Manager\n")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("Make sure you pasted the complete URL from your browser")