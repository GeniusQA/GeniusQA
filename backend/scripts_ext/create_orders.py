import hmac
import hashlib
import time
import json
import requests

API_SECRET = "7d5bcedf57f6460f20e22895532273f695ec940acb3bf118"
MERCHANT_ID = "MCH007881CF6E42C6"
API_KEY = "sk_d987cc44b7ae5bef0b15618a"

url = "https://yastapayadmin.aitechprod.xyz/api/payment/create_orders"
payload = {"amount": "100", "symbol": "usd", "expired_time": 3600}

# 1. 生成签名：body 文本 + "|" + timestamp，再做 HMAC-SHA256
body_text = json.dumps(payload, ensure_ascii=False)
timestamp = str(int(time.time()))
sign_string = body_text + "|" + timestamp
signature = hmac.new(API_SECRET.encode(), sign_string.encode(), hashlib.sha256).hexdigest()

# 2. 组装请求头（动态填入 X-SIGN / X-TIMESTAMP）
headers = {
    "User-Agent": "python-requests/2.32.5",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "X-MERCHANT-ID": MERCHANT_ID,
    "X-API-KEY": API_KEY,
    "X-SIGN": signature,
    "X-TIMESTAMP": timestamp,
    "Content-Type": "application/json",
}

# 3. 发送请求（用 json= 自动序列化为 JSON 并计算 Content-Length）
response = requests.request("POST", url, headers=headers, json=payload)
print("status:", response.status_code)
print("response:", response.text)
