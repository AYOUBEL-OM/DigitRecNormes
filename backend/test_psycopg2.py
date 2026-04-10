# backend/test_psycopg2.py
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Load DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
print(f"🔍 DATABASE_URL: {'✅ Loaded' if DATABASE_URL else '❌ Missing'}")

if not DATABASE_URL:
    print("❌ Add DATABASE_URL to your .env file!")
    exit(1)

# Parse the URL manually to show components (for debugging)
# Format: postgresql://user:pass@host:port/db?sslmode=require
try:
    # Remove postgresql://
    rest = DATABASE_URL.replace("postgresql://", "")
    
    # Split user:pass@host
    auth_host, db_part = rest.rsplit("@", 1)
    user_pass, host_port = auth_host.split(":", 1)
    user, password = user_pass.split(":", 1) if ":" in user_pass else (user_pass, "")
    
    print(f"👤 User: {user}")
    print(f"🔐 Password: {'*' * len(password)} (length: {len(password)})")
    print(f"🌐 Host/Port: {host_port}")
    print(f"🗄️  Database: {db_part}")
except Exception as e:
    print(f"⚠️  Could not parse URL: {e}")

print("\n🔗 Attempting direct psycopg2 connection...")

try:
    # Try direct connection with psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"✅ SUCCESS! Connected to: {version[:60]}...")
    cur.close()
    conn.close()
    
except psycopg2.OperationalError as e:
    print(f"❌ psycopg2 OperationalError!")
    print(f"🔍 Full error: {e}")
    print(f"🔍 Error args: {e.args}")
    
    # Common fixes
    err_str = str(e).lower()
    if "password" in err_str or "authentication" in err_str:
        print("\n💡 FIX: Password issue!")
        print("   - Check if @ in password is encoded as %40")
        print("   - Try resetting password in Supabase Dashboard")
    elif "ssl" in err_str or "tls" in err_str:
        print("\n💡 FIX: SSL issue!")
        print("   - Add ?sslmode=require to DATABASE_URL")
    elif "db." not in DATABASE_URL:
        print("\n💡 FIX: Host format!")
        print("   - Use: db.xxx.supabase.co (NOT xxx.supabase.co)")
    elif "timeout" in err_str or "connection refused" in err_str:
        print("\n💡 FIX: Network issue!")
        print("   - Check internet connection")
        print("   - Try pinging: db.rhedlvxkmbugidditvow.supabase.co")
        
except Exception as e:
    print(f"❌ Unexpected error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()