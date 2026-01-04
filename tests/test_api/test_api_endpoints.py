"""測試不同的 TWSE API 端點，確認哪個可用"""
import requests
import time
from datetime import datetime

def test_api_endpoint(url, params, description):
    """測試 API 端點"""
    print(f"\n{'='*60}")
    print(f"測試: {description}")
    print(f"URL: {url}")
    print(f"參數: {params}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"狀態碼: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"響應類型: {type(data)}")
                if isinstance(data, dict):
                    print(f"響應鍵: {list(data.keys())[:10]}")
                print("✓ 成功")
                return True
            except:
                print(f"響應內容 (前200字符): {response.text[:200]}")
                print("✓ 成功 (非JSON)")
                return True
        else:
            print(f"✗ 失敗: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ 錯誤: {str(e)}")
        return False

if __name__ == "__main__":
    print("開始測試 TWSE API 端點...")
    
    base_url = "https://www.twse.com.tw/rwd/zh/afterTrading"
    
    # 測試不同的端點
    endpoints = [
        {
            "url": f"{base_url}/MI_INDEX",
            "params": {"date": "20250828", "type": "ALL", "response": "json"},
            "description": "MI_INDEX - 所有股票數據"
        },
        {
            "url": f"{base_url}/MI_INDEX",
            "params": {"date": "20250828", "type": "IND", "response": "json"},
            "description": "MI_INDEX - 產業指數"
        },
        {
            "url": "https://www.twse.com.tw/rwd/zh/fund/T86",
            "params": {"date": "20250828", "selectType": "ALL", "response": "json"},
            "description": "T86 - 三大法人買賣"
        },
        {
            "url": "https://www.twse.com.tw/rwd/zh/fund/MI_INDEX",
            "params": {"date": "20250828", "type": "ALL", "response": "json"},
            "description": "fund/MI_INDEX - 基金數據"
        }
    ]
    
    results = []
    for endpoint in endpoints:
        result = test_api_endpoint(
            endpoint["url"],
            endpoint["params"],
            endpoint["description"]
        )
        results.append((endpoint["description"], result))
        time.sleep(1)  # 避免請求過快
    
    print(f"\n{'='*60}")
    print("測試結果總結:")
    for desc, result in results:
        status = "✓" if result else "✗"
        print(f"{status} {desc}")

