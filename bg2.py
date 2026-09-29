import time
import json
import uuid
import re
import random
import requests
import redis
import urllib3
import secrets
import hashlib
import base64
import urllib.parse
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
REDIS_URL = "redis://default:DWYgsUKwUJTjTMQpasIEHBYVPEMMhoPt@altaria.proxy.rlwy.net:22748"

def normalize_phone(phone_str):
    p = str(phone_str).strip()
    return "0" + p if p.startswith("9") and len(p) == 10 else p

def generate_pkce():
    verifier = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(hashed).decode('ascii').rstrip('=')
    return verifier, challenge

class ProxyManager:
    def __init__(self, proxies):
        self.proxies = [{"url": p, "uses": 0, "next_available": 0} for p in proxies]
        self.lock = threading.Lock()

    def get_proxy(self):
        while True:
            with self.lock:
                now = time.time()
                available = [p for p in self.proxies if p["uses"] < 4 and p["next_available"] <= now]
                if available:
                    chosen = available[0]
                    chosen["uses"] += 1
                    chosen["next_available"] = now + 15 
                    return chosen["url"]
                
                if all(p["uses"] >= 4 for p in self.proxies):
                    return None
            time.sleep(1)

class NexusBridgeAgent:
    def __init__(self):
        print("======================================================")
        print(" 🚀 Nexus Extractor - DIGIKALA SECURE BULK MODE 🚀 ")
        print("======================================================")
        self.db = self.connect_redis()
        self.device_lock = threading.Lock()
        
    def connect_redis(self):
        while True:
            try:
                db = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                db.ping()
                print("✅ Connected to Cloud Redis.")
                return db
            except Exception:
                time.sleep(5)

    def send_alert_to_admin(self, text):
        try:
            self.db.rpush("bot:admin_alerts", text)
        except Exception:
            pass

    def send_file_to_admin(self, filename, content):
        try:
            file_data = {"filename": filename, "content": content}
            self.db.rpush("bot:admin_files", json.dumps(file_data, ensure_ascii=False))
        except Exception:
            pass

    def get_active_proxies(self):
        try:
            res = requests.get("http://127.0.0.1:2525/proxies/active", timeout=5)
            data = res.json()
            raw_list = data.get("proxies", []) if isinstance(data, dict) else []
            if not raw_list:
                raw_list = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)', res.text)
            proxies = [f"http://{p}" if not p.startswith("http") else p for p in set(raw_list)]
            print(f"🔍 تعداد {len(proxies)} پروکسی آماده به کار دریافت شد.")
            return proxies
        except Exception as e:
            print(f"❌ خطای دریافت پروکسی: {e}")
            return []

    def get_all_phones_from_device(self):
        try:
            res = requests.get("http://127.0.0.1:11188/api.jsp?act=getPortList", timeout=5).json()
            if res.get("Code") == "1":
                return [normalize_phone(p.get("Phone")) for p in res.get("List", []) if p.get("Phone")]
        except Exception:
            pass
        return []

    def wait_for_sms(self, target_phone, timeout=50):
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.device_lock:
                try:
                    res = requests.get("http://127.0.0.1:11188/api.jsp?act=getSmsList&StartID=0", timeout=5).json()
                    if res.get("Code") == "1":
                        for sms in reversed(res.get("List", [])):
                            if normalize_phone(sms.get("Phone", "")) == target_phone:
                                msg = sms.get("Message", "")
                                if "دیجی" in msg or "digi" in msg.lower():
                                    match = re.search(r'\b\d{5,6}\b', msg)
                                    if match: return match.group()
                except Exception:
                    pass
            time.sleep(3)
        return None

    def process_single_phone(self, phone, proxy_manager):
        logs = [f"====== [ شروع عملیات استخراج برای: {phone} ] ======"]
        proxy_url = proxy_manager.get_proxy()
        
        if not proxy_url:
            logs.append("❌ خطا: ظرفیت پروکسی تکمیل شد.")
            return phone, "error", "ظرفیت پروکسی تکمیل شد", "\n".join(logs)
            
        logs.append(f"🌐 Proxy in use: {proxy_url}")

        session = requests.Session()
        session.proxies = {"http": proxy_url, "https": proxy_url}
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fa,en-US;q=0.7,en;q=0.3'
        })

        verifier, challenge = generate_pkce()
        nonce = secrets.token_urlsafe(16)
        state = secrets.token_urlsafe(16)
        redirect_uri = "https://www.digikala.com/sso-redirect/?back-url=%2Fprofile%2F"

        auth_url = (
            "https://auth.digikala.com/realms/dk-group/protocol/openid-connect/auth"
            f"?client_id=digikala-web-public&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}&state={state}"
            f"&code_challenge={challenge}&code_challenge_method=S256"
        )

        try:
            res = session.get(auth_url, timeout=15)
            logs.append(f"▶️ GET Auth URL | Status: {res.status_code}")
            
            if res.status_code == 403:
                return phone, "error", "مسدود شدن پروکسی توسط دیجی‌کالا (403)", "\n".join(logs)

            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            
            if not form: 
                return phone, "error", "فرم ورود یافت نشد", "\n".join(logs)
                
            action_url = form.get('action')
            res = session.post(action_url, data={"username": phone, "rememberMe": "on"}, timeout=15)
            logs.append(f"◀️ POST Phone Response | Status: {res.status_code}")
            soup = BeautifulSoup(res.text, 'html.parser')

            if soup.find('input', {'name': 'password'}) or soup.find('input', {'type': 'password'}):
                otp_exec_input = soup.find('input', {'id': 'otp-auth-execution'})
                if otp_exec_input and otp_exec_input.has_attr('value'):
                    exec_value = otp_exec_input['value']
                    form_login = soup.find('form', {'id': 'dk-form-login'})
                    form_action = form_login.get('action') if form_login else action_url
                    res = session.post(form_action, data={"authenticationExecution": exec_value}, timeout=15)
                    soup = BeautifulSoup(res.text, 'html.parser')
                else:
                    return phone, "error", "خطای ساختار فرم رمز", "\n".join(logs)

            form_otp = soup.find('form')
            if not form_otp: 
                return phone, "error", "فرم پیامک یافت نشد", "\n".join(logs)
                
            otp_action_url = form_otp.get('action')
            code = self.wait_for_sms(phone, timeout=50)
            if not code: 
                return phone, "error", "تایم‌اوت پیامک", "\n".join(logs)

            res = session.post(otp_action_url, data={"code": code}, allow_redirects=False, timeout=15)

            auth_code = None
            if 'Location' in res.headers:
                cmatch = re.search(r'code=([^&]+)', res.headers['Location'])
                if cmatch: auth_code = cmatch.group(1)
            if not auth_code:
                cmatch = re.search(r'code=([^&]+)', res.text)
                if cmatch: auth_code = cmatch.group(1)

            if not auth_code: 
                return phone, "error", "کد تایید اشتباه است", "\n".join(logs)

            token_data = {
                "code": auth_code,
                "grant_type": "authorization_code",
                "client_id": "digikala-web-public",
                "redirect_uri": redirect_uri,
                "code_verifier": verifier
            }
            res_token = session.post("https://auth.digikala.com/realms/dk-group/protocol/openid-connect/token", data=token_data, timeout=15)

            if res_token.status_code == 200:
                tokens = res_token.json()
                access_token = tokens.get('access_token')
                refresh_token = tokens.get('refresh_token')
                
                session.cookies.set("Digikala:User:Token:v2", access_token, domain=".api.digikala.com", path="/", secure=True)
                if refresh_token:
                    session.cookies.set("Digikala:User:Refresh:Token:v2", refresh_token, domain=".api.digikala.com", path="/v1/user/", secure=True)

                extension_cookies = []
                for cookie in session.cookies:
                    cookie_data = {
                        "domain": cookie.domain,
                        "hostOnly": not cookie.domain.startswith('.'),
                        "httpOnly": 'HttpOnly' in cookie._rest if cookie._rest else False,
                        "name": cookie.name,
                        "path": cookie.path,
                        "sameSite": "lax",
                        "secure": cookie.secure or True,
                        "session": cookie.expires is None,
                        "storeId": "0",
                        "value": cookie.value,
                        "expirationDate": int(time.time()) + (30 * 24 * 60 * 60)
                    }
                    extension_cookies.append(cookie_data)

                final_json = {"cookies": extension_cookies, "origins": []}
                payload = {"phone": phone, "name": "کاربر دیجی‌کالا", "data": final_json}
                self.db.rpush("bot:new_accounts", json.dumps(payload, ensure_ascii=False))
                self.db.sadd("jet:processed_phones", phone)
                return phone, "success", "کاربر دیجی‌کالا", "\n".join(logs)
            else:
                return phone, "error", "خطا در دریافت توکن", "\n".join(logs)

        except Exception as e:
            return phone, "error", str(e)[:30], "\n".join(logs)

    # ------------------ سیستم جدید چکر سوابق خرید ------------------
    def process_single_check(self, phone, acc_data, proxy_manager):
        proxy_url = proxy_manager.get_proxy()
        
        # استخراج توکن از دیتا
        dk_token = None
        for cookie in acc_data.get("data", {}).get("cookies", []):
            if cookie.get("name") == "Digikala:User:Token:v2":
                dk_token = cookie.get("value")
                break
                
        if not dk_token:
            return phone, 0, "NO_TOKEN_IN_DATA"

        session = requests.Session()
        if proxy_url:
            session.proxies = {"http": proxy_url, "https": proxy_url}
            
        sa_headers = {
            "x-web-client": "desktop", "x-web-client-id": "web", "x-web-optimize-response": "1",
            "Referer": "https://www.digikala.com/",
            "Authorization": f"Bearer {dk_token}" if not dk_token.startswith("Bearer") else dk_token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            res_sa = session.get("https://api.digikala.com/super-app/v1/sso/jet/", params={"redirect_url": "/?utm_source=digikala-superweb"}, headers=sa_headers, allow_redirects=False, timeout=15, verify=False)
            sa_token = None
            if 'Location' in res_sa.headers:
                match = re.search(r'sa_token=([^&]+)', res_sa.headers['Location'])
                if match: sa_token = match.group(1)

            if not sa_token:
                res_sa_redirect = session.get("https://api.digikala.com/super-app/v1/sso/jet/", params={"redirect_url": "/?utm_source=digikala-superweb"}, headers=sa_headers, allow_redirects=True, timeout=15, verify=False)
                parsed = urllib.parse.urlparse(res_sa_redirect.url)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'sa_token' in qs: sa_token = qs['sa_token'][0]

            if not sa_token: return phone, 0, "SA_TOKEN_FAILED"

            jet_headers = {
                'authority': 'api.digikalajet.ir', 'accept': 'application/json, text/plain, */*',
                'app-id': '470de285-a905-462b-b967-53ce8eced716', 'client': 'mobile',
                'clientid': 'FINGERPRINTV2-' + uuid.uuid4().hex, 'clientos': 'Android',
                'content-type': 'application/json', 'origin': 'https://www.digikalajet.com',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile'
            }

            res_jet = session.post("https://api.digikalajet.ir/super-app-sso/", headers=jet_headers, json={"dsa_token": sa_token}, timeout=15, verify=False)
            if res_jet.status_code != 200: return phone, 0, f"JET_SSO_FAILED_{res_jet.status_code}"

            jet_token = res_jet.json().get('data', {}).get('token')
            if not jet_token: return phone, 0, "NO_JET_TOKEN"

            jet_headers['Authorization'] = jet_token
            jet_headers['session'] = f"{uuid.uuid4()}-V3*{int(time.time())}"

            res_orders = session.get("https://api.digikalajet.ir/order-shipments/?ch=jj", headers=jet_headers, timeout=15, verify=False)
            if res_orders.status_code == 200:
                res_json = res_orders.json()
                if res_json.get("status") == 200:
                    data_obj = res_json.get("data", {})
                    pager_total = data_obj.get("pager", {}).get("total_items", 0)
                    orders_obj = data_obj.get("orders", {})
                    ongoing = len(orders_obj.get("ongoing", []) or [])
                    accomplished = len(orders_obj.get("accomplished", []) or [])
                    total_orders = max(pager_total, ongoing + accomplished)
                    
                    # ثبت نتیجه در دیتابیس
                    acc_data["total_orders"] = total_orders
                    if total_orders > 0:
                        self.db.hset("jet:ordered_accounts", phone, json.dumps(acc_data, ensure_ascii=False))
                    else:
                        self.db.hset("jet:clean_accounts", phone, json.dumps(acc_data, ensure_ascii=False))
                    
                    self.db.hdel("jet:bulk_accounts", phone)
                    return phone, total_orders, "SUCCESS"
                else: return phone, 0, f"API_ERR_{res_json.get('status')}"
            else: return phone, 0, f"HTTP_{res_orders.status_code}"
                
        except Exception as e:
            return phone, 0, "TIMEOUT_OR_PROXY_ERR"

    def run_checker(self):
        proxies = self.get_active_proxies()
        raw_accounts = self.db.hgetall("jet:bulk_accounts")
        
        if not proxies:
            self.send_alert_to_admin("❌ توقف چکر: هیچ پروکسی فعالی یافت نشد.")
            return
        if not raw_accounts:
            self.send_alert_to_admin("❌ توقف چکر: اکانتی برای بررسی وجود ندارد.")
            return

        target_accounts = list(raw_accounts.items())
        capacity = len(proxies) * 4
        
        start_msg = f"🔎 **شروع چکر خریدها:**\nتعداد اکانت: {len(target_accounts)}\nپروکسی‌های فعال: {len(proxies)} (ظرفیت: {capacity})\n⏳ در حال بررسی (با استفاده از پروکسی‌های ثبت‌نام)..."
        print(start_msg)
        self.send_alert_to_admin(start_msg)

        pm = ProxyManager(proxies)
        ordered_count, clean_count, err_count = 0, 0, 0
        
        with ThreadPoolExecutor(max_workers=min(len(proxies), 20)) as executor:
            futures = []
            for phone, acc_raw in target_accounts:
                acc_data = json.loads(acc_raw)
                futures.append(executor.submit(self.process_single_check, phone, acc_data, pm))

            for future in as_completed(futures):
                phone, order_count, status = future.result()
                if status == "SUCCESS":
                    if order_count > 0: ordered_count += 1
                    else: clean_count += 1
                else:
                    err_count += 1

        end_msg = f"📊 **گزارش نهایی چکر:**\n⭐ دارای خرید: {ordered_count}\n⚪ بدون خرید (خام): {clean_count}\n❌ ارورها: {err_count}\n\nبررسی به اتمام رسید."
        print("\n" + end_msg)
        self.send_alert_to_admin(end_msg)

    def run_bulk(self):
        proxies = self.get_active_proxies()
        all_phones = self.get_all_phones_from_device()
        
        if not proxies:
            self.send_alert_to_admin("❌ توقف سیستم: هیچ پروکسی فعالی یافت نشد.")
            return
        if not all_phones:
            self.send_alert_to_admin("❌ توقف سیستم: هیچ شماره‌ای یافت نشد.")
            return

        processed = self.db.smembers("jet:processed_phones")
        target_phones = [p for p in all_phones if p not in processed]
        
        if not target_phones:
            self.send_alert_to_admin("✅ عملیات لغو شد: تمام شماره‌ها قبلاً پردازش شده‌اند.")
            return

        capacity = len(proxies) * 4
        if len(target_phones) > capacity:
            self.send_alert_to_admin(f"⛔️ **توقف سیستم (کمبود پروکسی)**\nشماره‌ها: {len(target_phones)}\nظرفیت پروکسی: {capacity}\n\nلطفاً تعداد پروکسی را افزایش دهید.")
            return

        start_report = f"🚀 **گزارش شروع عملیات استخراج:**\nتعداد پروکسی: {len(proxies)} (ظرفیت: {capacity}) | شماره‌ها: {len(target_phones)}\n⏳ در حال پردازش..."
        print(start_report)
        self.send_alert_to_admin(start_report)

        pm = ProxyManager(proxies)
        success_count, error_count = 0, 0
        full_logs = []
        
        with ThreadPoolExecutor(max_workers=min(len(proxies), 20)) as executor:
            futures = [executor.submit(self.process_single_phone, phone, pm) for phone in target_phones]
            for future in as_completed(futures):
                phone, status, msg, p_log = future.result()
                full_logs.append(p_log)
                if status == "success":
                    success_count += 1
                else:
                    error_count += 1

        end_report = f"📊 **گزارش نهایی استخراج:**\n✅ موفق: {success_count}\n❌ ارورها: {error_count}\n\nعملیات با موفقیت به اتمام رسید."
        print("\n" + end_report)
        self.send_alert_to_admin(end_report)
        
        if full_logs:
            file_content = "\n\n" + ("="*50) + "\n\n".join(full_logs)
            filename = f"Nexus_Debug_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            self.send_file_to_admin(filename, file_content)

    def run(self):
        print("🟢 Listening for ADMIN COMMANDS...")
        while True:
            try:
                task = self.db.blpop("bot:admin_commands", timeout=5)
                if task:
                    cmd = task[1]
                    if cmd == "START_BULK":
                        self.run_bulk()
                    elif cmd == "START_CHECKER":
                        self.run_checker()
            except Exception:
                time.sleep(2)

def check_license():
    url = "https://erlink.s3.ir-thr-at1.arvanstorage.ir/ls.txt?versionId="
    print("🔄 در حال بررسی دسترسی و لایسنس...")
    try:
        response = requests.get(url, timeout=10)
        if response.text.strip().lower() == "ok":
            print("✅ لایسنس تایید شد! برنامه آماده به کار است.\n")
            return True
        else:
            print("❌ دسترسی مسدود است! لایسنس نامعتبر یا منقضی شده است.")
            time.sleep(5)
            return False
    except Exception as e:
        print(f"❌ خطا در ارتباط با سرور لایسنس. لطفا اینترنت خود را بررسی کنید.")
        time.sleep(5)
        return False

if __name__ == "__main__":
    if check_license():
        NexusBridgeAgent().run()
    else:
        sys.exit()
