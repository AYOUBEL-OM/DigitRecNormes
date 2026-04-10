# backend/debug_db.py - ADVANCED DEBUG
import os
import sys
import socket
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
print("🔍 === Advanced Supabase Debugger ===\n")

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in .env")
    sys.exit(1)

# Parse URL manually
try:
    url_part = DATABASE_URL.replace("postgresql://", "")
    auth, rest = url_part.split("@", 1)
    user, password = auth.split(":", 1)
    host_port, db = rest.split("/", 1)
    host, port = host_port.split(":", 1)
    port = int(port)
    
    print(f"📡 Parsed connection:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   DB: {db}")
    print(f"   User: {user}")
    print(f"   Password: {'*' * len(password)}\n")
except Exception as e:
    print(f"❌ Failed to parse URL: {e}")
    sys.exit(1)

# 1. Test TCP Connection (Network level)
print("1️⃣ Testing TCP connection (port 5432)...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    result = sock.connect_ex((host, port))
    if result == 0:
        print("   ✅ TCP Port 5432 is OPEN (network OK)")
    else:
        print(f"   ❌ TCP Port 5432 is CLOSED (error code: {result})")
        print("   💡 Check firewall or internet connection")
    sock.close()
except Exception as e:
    print(f"   ❌ TCP test failed: {e}")

# 2. Try psycopg2 with URL
print(f"\n2️⃣ Testing psycopg2 with DATABASE_URL...")
try:
    import psycopg2
    print("   ⏳ Connecting...")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print(f"   ✅ SUCCESS with URL!")
    cur.close()
    conn.close()
    
except psycopg2.OperationalError as e:
    print(f"   ❌ psycopg2 OperationalError")
    print(f"   🔍 e: {e}")
    print(f"   🔍 e.args: {e.args}")
    print(f"   🔍 str(e): '{str(e)}'")
    print(f"   🔍 repr(e): {repr(e)}")
    
    # Check for empty error
    if not str(e).strip():
        print(f"\n   ⚠️  ERROR MESSAGE IS EMPTY!")
        print(f"   This usually means:")
        print(f"   - SSL/TLS handshake failed")
        print(f"   - Windows firewall blocking")
        print(f"   - Antivirus interfering")
    
except ImportError:
    print("   ❌ psycopg2 not installed: pip install psycopg2-binary")
except Exception as e:
    print(f"   ❌ Unexpected: {type(e).__name__}: {e}")

# 3. Try with EXPLICIT parameters (no URL)
print(f"\n3️⃣ Testing psycopg2 with explicit parameters...")
try:
    import psycopg2
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=db,
        user=user,
        password=password,
        sslmode="require",
        connect_timeout=10
    )
    print(f"   ✅ SUCCESS with explicit params!")
    conn.close()
except psycopg2.OperationalError as e:
    print(f"   ❌ Failed with explicit params")
    print(f"   🔍 Error: {e}")
    print(f"   🔍 Args: {e.args}")
except Exception as e:
    print(f"   ❌ Unexpected: {type(e).__name__}: {e}")

# 4. Try WITHOUT SSL (just for testing - Supabase will reject but we'll see the error)
print(f"\n4️⃣ Testing WITHOUT sslmode (to see real auth error)...")
try:
    import psycopg2
    # Remove sslmode from URL temporarily
    test_url = DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")
    conn = psycopg2.connect(test_url, connect_timeout=5)
    print(f"   ⚠️  Connected without SSL (unexpected!)")
    conn.close()
except psycopg2.OperationalError as e:
    err_str = str(e).lower()
    if "ssl" in err_str or "encrypted" in err_str or "tls" in err_str:
        print(f"   ✅ Expected: Supabase requires SSL")
        print(f"   🔍 Full error: {e}")
    else:
        print(f"   🔍 Got different error (maybe auth?): {e}")
except Exception as e:
    print(f"   ❌ Unexpected: {type(e).__name__}: {e}")

print(f"\n🏁 Debug completed!")
print(f"\n💡 If ALL tests fail with empty errors:")
print(f"   1. Try disabling Windows Firewall temporarily")
print(f"   2. Try running as Administrator")
print(f"   3. Try a different network (mobile hotspot)")
print(f"   4. Update psycopg2: pip install --upgrade psycopg2-binary")